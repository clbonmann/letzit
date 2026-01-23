from sqlalchemy import text
from app.db import AsyncSessionLocal # Use sua conexão de banco aqui
from app.core import celery_app

async def update_expired_offers_task():
    """
    Altera o status das ofertas para EXPIRED'.
    """
    async with AsyncSessionLocal() as db:
        try:
            EXPIRE_SQL = text("""
                UPDATE offers
                 SET status = 'EXPIRED',
                    status_reason = 'AUTO_EXPIRED',
                    status_changed_by_staff_id = NULL
                WHERE end_at IS NOT NULL
                AND end_at <= now()
                AND status IN ('CREATED', 'ACTIVE', 'PAUSED');
            """)
            await db.execute(EXPIRE_SQL)
            await db.commit()
            print("Ofertas alteradas para EXPIRED com sucesso.")
        except Exception as e:
            await db.rollback()
            print(f"Erro ao atualizar ofertas: {e}")
