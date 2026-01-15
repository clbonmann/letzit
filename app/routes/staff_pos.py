from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
# Importe sua dependência de autenticação do Staff
# Ajuste o import conforme onde ficou sua função get_current_staff_user
from app.deps import get_current_staff_user 

router = APIRouter(prefix="/staff/pos", tags=["staff-pos"])

class RedeemRequest(BaseModel):
    # O ID do convite (target) que está no QR Code do cliente
    offer_target_id: int

@router.post("/redeem")
async def redeem_offer(
    payload: RedeemRequest,
    current_staff: dict = Depends(get_current_staff_user),
    db: AsyncSession = Depends(get_db_session),
):
    """
    VALIDAR CUPOM (Ação do Garçom):
    1. Verifica se o cupom existe.
    2. Verifica se pertence a ESTE restaurante (Segurança).
    3. Verifica se já não foi usado antes (Anti-Fraude).
    4. Marca como usado e atualiza estoques.
    """
    
    # 1. Busca dados do Convite + Oferta
    query = text("""
        SELECT 
            t.id, 
            t.offer_id, 
            t.user_id, 
            t.used_at,
            o.restaurant_id,
            o.title,
            o.price_cents,
            u.name as user_name,
            u.phone_e164
        FROM offer_targets t
        JOIN offers o ON o.id = t.offer_id
        JOIN users u ON u.id = t.user_id
        WHERE t.id = :tid
    """)
    
    result = await db.execute(query, {"tid": payload.offer_target_id})
    row = result.mappings().first()
    
    # --- CAMADA DE VALIDAÇÃO ---

    # A. Existe?
    if not row:
        raise HTTPException(
            status_code=404, 
            detail="Cupom inválido ou não encontrado."
        )
        
    # B. É deste restaurante? (A trava mais importante)
    # Se o staff logado for do restaurante 10 e tentar ler cupom do 20, bloqueia.
    if row.restaurant_id != current_staff["restaurant_id"]:
        raise HTTPException(
            status_code=403, 
            detail="ESTE CUPOM PERTENCE A OUTRO RESTAURANTE! Não é possível validar."
        )
        
    # C. Já foi usado?
    if row.used_at is not None:
        # Formata a data para mostrar quando foi usado (opcional, mas útil)
        used_formatted = row.used_at.strftime("%d/%m às %H:%M")
        raise HTTPException(
            status_code=409, 
            detail=f"CUPOM JÁ UTILIZADO em {used_formatted}."
        )

    # --- CAMADA DE EXECUÇÃO ---

    try:
        # 2. Marca o target como usado (TIMESTAMP atual)
        await db.execute(text("""
            UPDATE offer_targets 
            SET used_at = NOW()
            WHERE id = :tid
        """), {"tid": payload.offer_target_id})
        
        # 3. Incrementa o contador global da oferta (Claimed Count)
        # Isso serve para analytics e para travar ofertas com estoque limitado
        await db.execute(text("""
            UPDATE offers 
            SET claimed_count = claimed_count + 1
            WHERE id = :oid
        """), {"oid": row.offer_id})
        
        await db.commit()
        
    except Exception as e:
        await db.rollback()
        print(f"Erro no Redeem: {e}")
        raise HTTPException(status_code=500, detail="Erro ao validar cupom.")

    # 4. Retorno de Sucesso (O que aparece na tela do garçom)
    return {
        "status": "success",
        "message": "VALIDADO COM SUCESSO!",
        "data": {
            "offer_title": row.title,
            "client_name": row.user_name,
            "price_to_charge": row.price_cents, # O garçom vê quanto cobrar
            "validated_at": datetime.now()
        }
    }
