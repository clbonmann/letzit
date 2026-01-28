from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update, desc
from fastapi import HTTPException
from app.models import Restaurant, RestaurantAccount

async def process_transaction(
    db: AsyncSession,
    restaurant_id: int,
    amount: int, # Positivo = Compra (Entrada), Negativo = Gasto (Saída)
    value: float, # Valor pago em REAIS (Só usado se amount > 0)
    description_data: dict 
) -> RestaurantAccount:
    
    amount = amount or 0
    # 1. LOCK (Trava de Segurança) 🔒
    stmt_lock = select(Restaurant).where(Restaurant.id == restaurant_id).with_for_update()
    result_lock = await db.execute(stmt_lock)
    restaurant = result_lock.scalar_one_or_none()

    if not restaurant:
        raise HTTPException(404, "Restaurante não encontrado.")

    # 2. BUSCAR DADOS ANTERIORES
    stmt_last = (
        select(RestaurantAccount)
        .where(RestaurantAccount.restaurant_id == restaurant_id)
        .order_by(desc(RestaurantAccount.id))
        .limit(1)
    )
    result_last = await db.execute(stmt_last)
    last_account = result_last.scalar_one_or_none()
    
    # Extração segura de valores anteriores
    if last_account:
        previous_balance_km = last_account.balance_km
        previous_balance_cents = last_account.balance_cents
        previous_cost_km_cents = last_account.cost_km_cents
    else:
        # Cold Start (Primeira transação da vida)
        previous_balance_km = 0
        previous_balance_cents = 0
        previous_cost_km_cents = 0

    previous_balance_cents = previous_balance_cents or 0
    previous_balance_cents = previous_balance_cents or 0
    previous_balance_km = previous_balance_km or 0
    # 3. CÁLCULOS MATEMÁTICOS 🧮
    
    # Saldo de KM é simples: soma o amount (que pode ser negativo)
    new_balance_km = previous_balance_km + amount

    if new_balance_km < 0:
         raise HTTPException(400, "Saldo de KM insuficiente.")
    # A lógica se divide aqui: COMPRA vs GASTO
    if int(amount) > 0:
        # --- CENÁRIO A: COMPRA (Entrada de Estoque) ---
        # Aqui o Preço Médio Ponderado (PMP) é recalculado.
        
        value_cents = int(value * 100) # Transforma R$ em centavos
        
        # Novo Saldo em Centavos = O que tinha + O que entrou (dinheiro novo)
        new_balance_cents = previous_balance_cents + value_cents
        
        # Custo Médio = Valor Total em Dinheiro / Total de KMs
        if new_balance_km > 0:
            new_cost_km_cents = new_balance_cents / new_balance_km
        else:
            new_cost_km_cents = 0 # Evita divisão por zero
            
    else:
        # --- CENÁRIO B: GASTO (Saída de Estoque) ---
        # Quando gasta, o Preço Médio NÃO MUDA. O estoque sai pelo preço que vale.
        
        new_cost_km_cents = previous_cost_km_cents
        
        # O valor monetário sai proporcionalmente aos KMs gastos
        # abs(amount) * custo atual
        debit_cents = abs(amount) * previous_cost_km_cents
        new_balance_cents = int(previous_balance_cents - debit_cents)
        
        # Ajuste fino: Se zerou KM, zera cents (pra evitar sobrar 1 centavo por arredondamento)
        if new_balance_km == 0:
            new_balance_cents = 0

    
    # 4. Atualizar Tabela Mestra (Snapshot no Restaurante)
    # (Opcional: converter cents de volta pra float/Reais pro usuário ver fácil, ou manter int)
    restaurant.balance_km = new_balance_km
    # restaurant.balance_current_value = new_balance_cents / 100.0 (Se tiver esse campo)
    restaurant.updated_at = func.now()
    
    # 5. Desativar flag 'is_current' antiga
    await db.execute(
         update(RestaurantAccount)
        .where(RestaurantAccount.restaurant_id == restaurant_id)
        .where(RestaurantAccount.is_current == True)
        .values(is_current=False)
    )

    # 6. Criar Registro no Ledger
    ledger_entry = RestaurantAccount(
        restaurant_id=restaurant_id,
        
        credit=amount if amount > 0 else 0,
        debit=abs(amount) if amount < 0 else 0,
        
        balance_km=new_balance_km,
        balance_cents=int(new_balance_cents),
        
        # Guardamos o PMP atualizado (arredondado para int ou mantido float se seu banco permitir)
        # Sugestão: Se cost_km_cents for Integer no banco, cuidado com arredondamento prematuro.
        # O ideal para custo unitário é guardar Float ou Integer com precisão maior (ex: décimos de centavo).
        cost_km_cents=int(new_cost_km_cents), 
        description=description_data.get("package_name") or description_data.get("offer_name") or "Transação Genérica",

        cost_package_cents=int(value * 100) if value > 0 else 0,
        
        is_current=True,
        package_code=description_data.get("package_code"), # Ajustei para package_code conforme combinamos
        offer_id=description_data.get("offer_id"),
        is_reversed=description_data.get("is_reversed", False),
        reversed_at=description_data.get("reversed_at", None)
    )

    db.add(ledger_entry)
    
    return ledger_entry