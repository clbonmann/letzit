from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/admin/jobs", tags=["admin-jobs"])

NO_SHOW_REPUTATION_PENALTY = 20
NO_SHOW_COOLDOWN_HOURS = 24


@router.post("/no-show")
async def run_no_show_job(
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    """
    Executa job de NO-SHOW manualmente / via cron
    Protegido por staff auth
    """
    # opcional: só admin
    if staff["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin only")

    now = datetime.now(timezone.utc)
    processed = 0

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

        await db.execute(
            text("""
                UPDATE offer_claims
                SET status = 'NO_SHOW',
                    penalty_applied_at = :now
                WHERE id = :cid
            """),
            {"now": now, "cid": claim_id},
        )

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

        processed += 1

    await db.commit()

    return {"processed_no_shows": processed}
