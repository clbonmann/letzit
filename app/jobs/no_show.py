from datetime import datetime, timedelta, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import AsyncSessionLocal
from app.celery_app import celery_app


# parâmetros de negócio (ajuste depois)
NO_SHOW_REPUTATION_PENALTY = 20
NO_SHOW_COOLDOWN_HOURS = 24


@celery_app.task(name="no_show.process")
def process_no_shows() -> dict:
    """
    Marca ACCEPTED expirados como NO_SHOW
    Aplica penalidade no usuário
    """
    return _run_async()


def _run_async() -> dict:
    import asyncio
    return asyncio.run(_process())


async def _process() -> dict:
    now = datetime.now(timezone.utc)
    affected = 0

    async with AsyncSessionLocal() as db:
        async with db.begin():
            # 1) buscar claims expirados
            rows = (await db.execute(
                text("""
                    SELECT id, user_id
                    FROM offer_claims
                    WHERE status = 'ACCEPTED'
                      AND expires_at < :now
                """),
                {"now": now},
            )).mappings().all()

            for row in rows:
                claim_id = int(row["id"])
                user_id = int(row["user_id"])

                # 2) marcar claim como NO_SHOW
                await db.execute(
                    text("""
                        UPDATE offer_claims
                        SET status = 'NO_SHOW',
                            penalty_applied_at = :now
                        WHERE id = :cid
                    """),
                    {"now": now, "cid": claim_id},
                )

                # 3) aplicar penalidade ao usuário
                await db.execute(
                    text("""
                        UPDATE user_stats
                        SET no_show_count = no_show_count + 1
                        WHERE user_id = :uid
                    """),
                    {"uid": user_id},
                )

                await db.execute(
                    text("""
                        UPDATE users
                        SET reputation = GREATEST(0, reputation - :penalty),
                            cooldown_until = :cooldown
                        WHERE id = :uid
                    """),
                    {
                        "uid": user_id,
                        "penalty": NO_SHOW_REPUTATION_PENALTY,
                        "cooldown": now + timedelta(hours=NO_SHOW_COOLDOWN_HOURS),
                    },
                )

                affected += 1

        await db.commit()

    return {"processed_no_shows": affected}
