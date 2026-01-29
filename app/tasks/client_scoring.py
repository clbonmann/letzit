from celery import shared_task
import asyncio
from sqlalchemy import text
from app.db import AsyncSessionLocal
import logging
import math

logger = logging.getLogger(__name__)

async def calculate_client_scores_logic():
    async with AsyncSessionLocal() as db:
        try:
            logger.info("Iniciando cálculo de Level e Reputação...")

            # 1. Pega estatísticas de uso dos Tickets (Claims)
            # Consideramos 'EXPIRED' como No-Show (reservou e não usou)
            claims_sql = text("""
                SELECT 
                    client_id,
                    COUNT(*) FILTER (WHERE status = 'ACCEPTED' AND expires_at < NOW()) as count_noshow,
                    COUNT(*) FILTER (WHERE status = 'CONSUMED') as count_redeemed,
                    COUNT(*) FILTER (WHERE status = 'CANCELLED') as count_cancelled
                FROM offer_claims
                GROUP BY client_id
            """)
            claims_result = (await db.execute(claims_sql)).mappings().all()
            
            # Transforma em dicionário para acesso rápido
            stats = {row['client_id']: dict(row) for row in claims_result}

            # 2. Pega estatísticas de Avaliações (Reviews)
            reviews_sql = text("""
                SELECT client_id, COUNT(*) as count_reviews
                FROM store_reviews
                GROUP BY client_id
            """)
            reviews_result = (await db.execute(reviews_sql)).mappings().all()
            
            # Merge das reviews no dicionário de stats
            for row in reviews_result:
                cid = row['client_id']
                if cid not in stats:
                    stats[cid] = {'count_noshow': 0, 'count_redeemed': 0, 'count_cancelled': 0}
                stats[cid]['count_reviews'] = row['count_reviews']

            # 3. Processa e Atualiza Clientes
            updates = []
            
            for client_id, data in stats.items():
                redeemed = data.get('count_redeemed', 0)
                noshow = data.get('count_noshow', 0)
                cancelled = data.get('count_cancelled', 0)
                reviews = data.get('count_reviews', 0)

                # --- Lógica do Nível ---
                # "ceil do número de tickets redeemed dividido por 10"
                # Ex: 1 a 10 tickets = Nível 1. 11 tickets = Nível 2.
                raw_level = math.ceil(redeemed / 10)
                level = max(1, raw_level) # Garante no mínimo nível 1

                # --- Lógica da Reputação ---
                # Base 95
                score = 95
                
                # Ganhos
                score += (redeemed // 10) * 1  # +1 a cada 10 redeemed
                score += (reviews // 5) * 1    # +1 a cada 5 avaliações
                
                # Perdas
                # "Cada 5 redeemed sem avaliação" -> (Redeemed - Reviews) // 5
                # Só conta se redeemed > reviews (evitar negativo)
                unreviewed_count = max(0, redeemed - reviews)
                score -= (unreviewed_count // 5) * 1
                
                score -= (cancelled // 3) * 1  # -1 a cada 3 cancelamentos
                score -= (noshow * 1)          # -1 a cada 1 no-show
                
                # Limites (Cap em 100)
                final_reputation = min(100, score)
                
                # Regra de Bloqueio (< 80)
                is_blocked = final_reputation < 80

                updates.append({
                    "cid": client_id,
                    "lvl": level,
                    "rep": final_reputation,
                    "blk": is_blocked
                })

            # 4. Update em Batch no Banco
            # Usamos uma query com CASE para atualizar tudo de uma vez (muito mais performático)
            if updates:
                # Nota: Em produção massiva, faríamos updates parciais. 
                # Aqui faremos um loop simples para garantir compatibilidade com SQLAlchemy async
                for u in updates:
                    await db.execute(text("""
                        UPDATE clients 
                        SET level = :lvl, reputation = :rep, is_blocked = :blk
                        WHERE id = :cid
                    """), u)
                
                await db.commit()
                logger.info(f"Scores atualizados para {len(updates)} clientes.")

        except Exception as e:
            await db.rollback()
            logger.error(f"Erro no cálculo de score: {e}")

@shared_task(name="app.tasks.client_scoring.update_client_scores_task")
def update_client_scores_task():
    asyncio.run(calculate_client_scores_logic())