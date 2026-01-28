from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List

from app import db
from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.models import Restaurant, Packages

from app.schemas.staff import BuyPackageRequest, PackageResponse
from app.services.finance import process_transaction 

router = APIRouter(prefix="/staff/packages", tags=["Packages"])


@router.post("/buy")
async def buy_package(
    payload: BuyPackageRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    # 1. BUSCAR O PACOTE NO BANCO (Não mais no dicionário fixo)
    stmt = select(Packages).where(Packages.code == payload.package_code)
    result = await db.execute(stmt)
    package = result.scalar_one_or_none()

    # Validações
    if not package:
        raise HTTPException(400, "Pacote inválido ou não encontrado.")
    
    if not package.is_active:
        raise HTTPException(400, "Este pacote não está mais disponível para venda.")
    
    rid = int(staff["restaurant_id"])

    # 2. PROCESSAR A TRANSAÇÃO FINANCEIRA
    # O service 'process_transaction' já cuida de:
    # - Buscar o restaurante e travar a linha (lock)
    # - Somar o saldo anterior + novos créditos
    # - Criar o registro de histórico (Ledger)
    try:
        transaction = await process_transaction(
            db=db,
            restaurant_id=rid,
            amount=package.km, # Pega o valor da coluna 'km' do banco
            value=package.price,
            description_data={
                "package_code": package.code,     # Guarda qual foi o pacote
                "package_name": package.name    # Guarda o nome (útil se mudar depois)
            }
        )
        
        # 3. COMMIT (Salva tudo de uma vez: atualização do saldo + histórico)
        await db.commit()
        
        # 4. RETORNO PARA O FRONTEND
        return {
            "message": f"Sucesso! {package.name} adquirido.",
            "new_balance_km": transaction.balance_km, # O saldo atualizado
            "added_km": package.km,
            "paid_amount": package.price
        }

    except Exception as e:
        await db.rollback() # Se der erro no meio, desfaz tudo
        # Em produção, logue o erro real 'e' no console
        print(f"Erro na compra de pacote: {e}") 
        raise HTTPException(500, "Erro ao processar a transação. Tente novamente.")
    

@router.get("/", response_model=List[PackageResponse])
async def list_packages(
    db: AsyncSession = Depends(get_db_session),
    # Opcional: Remova a linha abaixo se quiser que a loja seja pública (sem login)
    _current_staff: dict = Depends(get_current_staff) 
):
    """
    Lista todos os pacotes ativos para exibição na loja.
    Ordena por preço (do mais barato para o mais caro).
    """
    stmt = (
        select(Packages)
        .where(Packages.is_active == True)
        .order_by(Packages.price.asc())
    )
    
    result = await db.execute(stmt)
    packages = result.scalars().all()
    
    return packages