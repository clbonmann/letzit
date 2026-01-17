from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.models import Restaurant
from app.constants.packages import PACKAGES

router = APIRouter(prefix="/staff/packages", tags=["Packages"])

# Schema simples para o request
class BuyPackageRequest(BaseModel):
    package_id: str # Ex: "PKG_STARTER"

@router.post("/buy")
async def buy_package(
    payload: BuyPackageRequest,
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    # 1. Validar se o pacote existe
    package = PACKAGES.get(payload.package_id)
    if not package:
        raise HTTPException(400, "Pacote inválido.")

    # 2. Buscar o Restaurante
    stmt = select(Restaurant).where(Restaurant.id == int(staff["restaurant_id"]))
    result = await db.execute(stmt)
    restaurant = result.scalar_one_or_none()

    if not restaurant:
        raise HTTPException(404, "Restaurante não encontrado.")

    # 3. ADICIONAR OS CRÉDITOS (A mágica acontece aqui)
    # Aqui entraria a integração com Stripe/Pagar.me.
    # Se o pagamento for aprovado:
    
    restaurant.balance_km += package["km"]
    
    # (Opcional) Registrar a transação financeira em uma tabela 'payments' para histórico
    
    await db.commit()
    await db.refresh(restaurant)

    return {
        "message": f"Sucesso! Você comprou {package['name']}.",
        "added_km": package["km"],
        "new_balance_km": restaurant.balance_km,
        "paid_amount": package["price"]
    }