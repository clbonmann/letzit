from sqlalchemy import text
from app.db import AsyncSessionLocal # Use sua conexão de banco aqui

async def update_restaurant_reputation_task():
    """
    Recalcula a média de avaliações de todos os restaurantes
    e atualiza a coluna 'reputation' na tabela 'restaurants'.
    """
    async with AsyncSessionLocal() as db:
        try:
            # Query atômica para recalcular e atualizar
            sql = text("""
                UPDATE restaurants r
                SET reputation = sub.avg_total
                FROM (
                    SELECT 
                        restaurant_id, 
                        ROUND(AVG(average_score)::numeric, 1) as avg_total
                    FROM restaurant_reviews
                    GROUP BY restaurant_id
                ) AS sub
                WHERE r.id = sub.restaurant_id;
            """)
            await db.execute(sql)
            await db.commit()
            print("Reputação dos restaurantes atualizada com sucesso.")
        except Exception as e:
            await db.rollback()
            print(f"Erro ao atualizar reputação: {e}")