from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

NO_SHOW_SQL = text("""
WITH penalized AS (
  UPDATE offer_claims
  SET
    status = 'NO_SHOW',
    penalty_applied_at = now()
  WHERE status = 'ACCEPTED'
    AND expires_at <= now()
    AND redeemed_at IS NULL
    AND canceled_at IS NULL
    AND penalty_applied_at IS NULL
  RETURNING user_id
)
UPDATE users u
SET cooldown_until = GREATEST(
    COALESCE(u.cooldown_until, now()),
    now() + make_interval(hours => :cooldown_hours)
)
FROM penalized p
WHERE u.id = p.user_id;
""")

COUNT_SQL = text("""
SELECT COUNT(*)::int
FROM offer_claims
WHERE status = 'NO_SHOW'
  AND penalty_applied_at >= now() - interval '5 minutes';
""")

async def run_no_show_job(db: AsyncSession, cooldown_hours: int = 24) -> dict:
    await db.execute(NO_SHOW_SQL, {"cooldown_hours": int(cooldown_hours)})
    await db.commit()

    # opcional: apenas “sensação” de que rodou (conta recentes)
    recent = (await db.execute(COUNT_SQL)).scalar_one()
    return {"ok": True, "cooldown_hours": int(cooldown_hours), "recent_no_shows_marked": int(recent)}
