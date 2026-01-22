from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_client import get_current_client_id 
from app.schemas.client import ClientProfileResponse, ClientUpdateProfileRequest, LocationUpdateSchema

router = APIRouter(prefix="/client/profile", tags=["client-profile"])

# --- 1. GET PERFIL ---
@router.get("", response_model=ClientProfileResponse)
async def get_my_profile(
    uid: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db_session),
):
    """Retorna dados do cliente logado."""
    query = text("SELECT id, name, phone_e164 as phone, email, avatar_url, birth_date, reputation, level, created_at FROM clients WHERE id = :uid")
    row = (await db.execute(query, {"uid": uid})).mappings().first()
    if not row: raise HTTPException(404, "Cliente não encontrado.")
    return ClientProfileResponse(**row)

# --- 2. UPDATE PERFIL ---
@router.patch("", response_model=ClientProfileResponse)
@router.patch("", response_model=ClientProfileResponse)
async def update_my_profile(
    payload: ClientUpdateProfileRequest,
    uid: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db_session),
):
    """Atualiza dados cadastrais."""
    fields, params = [], {"uid": uid}
    
    # 1. Nome
    if payload.name is not None: 
        fields.append("name = :name")
        params["name"] = payload.name
        
    # 2. Email (String vazia vira NULL no banco para não dar erro de unique em strings vazias)
    if payload.email is not None: 
        if payload.email == "": 
            fields.append("email = NULL") # Força null se vier vazio
        else:
            fields.append("email = :email")
            params["email"] = payload.email

    # 3. Avatar
    if payload.avatar_url is not None: 
        fields.append("avatar_url = :avatar")
        params["avatar"] = payload.avatar_url
        
    # 4. Data de Nascimento
    if payload.birth_date is not None: 
        fields.append("birth_date = :birth_date") # NOME UNIFICADO
        params["birth_date"] = payload.birth_date
    
    # Se não tem campos, retorna o perfil atual
    if not fields: 
        return await get_my_profile(uid, db)
    
    fields.append("updated_at = NOW()")
    
    # Query Montada
    query = text(f"""
        UPDATE clients 
        SET {', '.join(fields)} 
        WHERE id = :uid 
        RETURNING id, name, phone_e164 as phone, email, avatar_url, birth_date, reputation, level, created_at
    """)
    
    try:
        row = (await db.execute(query, params)).mappings().first()
        await db.commit()
        return ClientProfileResponse(**row)
        
    except Exception as e:
        await db.rollback()
        error_msg = str(e).lower()
        print(f"ERRO UPDATE PROFILE: {error_msg}") # Log no terminal para debug
        
        if "unique" in error_msg and "email" in error_msg:
            raise HTTPException(400, "Este e-mail já está em uso.")
        if "date" in error_msg or "time" in error_msg:
            raise HTTPException(400, "Formato de data inválido.")
            
        raise HTTPException(500, "Erro interno ao atualizar perfil.")

# --- 3. MEUS TICKETS (CRUCIAL PARA O APP) ---
@router.get("/tickets")
async def get_profile_tickets(
    uid: int = Depends(get_current_client_id), 
    db: AsyncSession = Depends(get_db_session)
):
    """
    Retorna lista unificada de tickets:
    1. Ativos (ACCEPTED) primeiro (por urgência).
    2. Histórico (USED, EXPIRED, NO_SHOW) depois (por data).
    """
    query = text("""
        SELECT 
            c.id as claim_id, c.qr_token, c.expires_at, c.accepted_at, c.created_at,
            o.title, o.price_cents, 
            r.name as restaurant_name, r.logo_url
        FROM offer_claims c
        JOIN offers o ON o.id = c.offer_id
        JOIN restaurants r ON r.id = o.restaurant_id
        WHERE c.client_id = :uid
        ORDER BY 
            CASE WHEN c.status = 'ACCEPTED' THEN 0 ELSE 1 END ASC,
            CASE WHEN c.status = 'ACCEPTED' THEN c.expires_at END ASC,
            c.created_at DESC
    """)
    rows = (await db.execute(query, {"uid": uid})).mappings().all()
    
    # Tratamento visual de NO-SHOW
    results = []
    now = datetime.now()
    for row in rows:
        r = dict(row)
        if r['status'] == 'ACCEPTED' and r['expires_at'] and r['expires_at'] < now:
            r['status'] = 'NO_SHOW'
        results.append(r)
        
    return results

# --- 4. LOCATION ---
@router.post("/location")
async def update_location(
    location_data: LocationUpdateSchema,
    uid: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db_session),
):
    """Atualiza GPS."""
    await db.execute(
        text("UPDATE clients SET geog = ST_SetSRID(ST_MakePoint(:long, :lat), 4326)::geography, last_loc_at = NOW(), loc_accuracy_m = :acc WHERE id = :uid"),
        {"lat": location_data.latitude, "long": location_data.longitude, "acc": location_data.accuracy, "uid": uid}
    )
    await db.commit()
    return {"status": "updated", "timestamp": datetime.now(timezone.utc)}

# --- 5. DELETE ACCOUNT ---
@router.delete("")
async def delete_account(
    uid: int = Depends(get_current_client_id),
    db: AsyncSession = Depends(get_db_session),
):
    try:
        await db.execute(text("DELETE FROM clients WHERE id = :uid"), {"uid": uid})
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(500, "Erro ao excluir conta.")
    return {"message": "Conta excluída."}