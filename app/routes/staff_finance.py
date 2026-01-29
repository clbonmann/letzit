from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from typing import List

from app.db import get_db_session
from app.deps_staff import get_current_staff # Sua dependência de auth
from app.models import StoreAccount, Store
from app.schemas import AccountHistoryResponse, BalanceResponse

# Importe o serviço que criamos acima
from app.services.finance import process_transaction 

router = APIRouter(prefix="/staff/finance", tags=["Financeiro"])

# --- ROTA 1: EXTRATO (Statement) ---
@router.get("/statement", response_model=List[AccountHistoryResponse])
async def get_statement(
    page: int = 1,
    limit: int = 20,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    rest_id = int(staff["store_id"])
    offset = (page - 1) * limit

    stmt = (
        select(StoreAccount)
        .where(StoreAccount.store_id == rest_id)
        .order_by(desc(StoreAccount.timestamp))
        .offset(offset)
        .limit(limit)
    )
    
    result = await db.execute(stmt)
    history = result.scalars().all()

    # Formatar resposta (enriquecer descrição)
    response_data = []
    for item in history:
        desc_text = "Movimentação"
        if item.package_id:
            desc_text = f"Compra de Pacote ({item.package_id})"
        elif item.offer_id:
            desc_text = f"Oferta Publicada #{item.offer_id}"
        elif item.is_returned:
            desc_text = "Estorno / Cancelamento"
        
        response_data.append({
            "id": item.id,
            "credit": item.credit,
            "debit": item.debit,
            "balance_km": item.balance_km,
            "timestamp": item.timestamp,
            "package_id": item.package_id,
            "offer_id": item.offer_id,
            "description": desc_text
        })

    return response_data

# --- ROTA 2: SALDO ATUAL (Rápida) ---
@router.get("/balance", response_model=BalanceResponse)
async def get_balance(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    rest_id = int(staff["store_id"])
    
    stmt = select(Store).where(Store.id == rest_id)
    result = await db.execute(stmt)
    store = result.scalar_one_or_none()
    
    if not store:
        raise HTTPException(404, "Store não encontrado")
        
    return {
        "balance_km": store.balance_km or 0.0,
        "last_update": store.updated_at # ou datetime.now()
    }

# --- ROTA 3: BÔNUS MANUAL (Apenas para ADMIN INTERNO ou Testes) ---
# Útil para você testar sem precisar passar cartão de crédito
from pydantic import BaseModel

class ManualAdjustment(BaseModel):
    amount_km: float # Pode ser negativo para remover
    reason: str

@router.post("/adjust")
async def manual_adjust(
    payload: ManualAdjustment,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    # Aqui você deve colocar uma proteção extra:
    # if staff["role"] != "INTERNAL_ADMIN": raise HTTPException(403)
    
    rest_id = int(staff["store_id"])
    
    try:
        # USA O SERVIÇO QUE CRIAMOS
        await process_transaction(
            db=db,
            store_id=rest_id,
            amount=payload.amount_km,
            description_data={"package_id": f"MANUAL: {payload.reason}"}
        )
        await db.commit()
        return {"status": "success", "message": "Saldo ajustado."}
    except Exception as e:
        await db.rollback()
        raise e