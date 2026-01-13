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
    if staff["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    # CTE (Common Table Expression) para fazer tudo de uma vez
    query = text("""
        WITH expired_claims AS (
            UPDATE offer_claims
            SET status = 'NO_SHOW', penalty_applied_at = now()
            WHERE status = 'ACCEPTED'
              AND expires_at < now()
            RETURNING user_id
        ),
        updated_stats AS (
            INSERT INTO user_stats (user_id, no_show_count)
            SELECT user_id, 1 FROM expired_claims
            ON CONFLICT (user_id) 
            DO UPDATE SET no_show_count = user_stats.no_show_count + 1
            RETURNING user_id
        )
        UPDATE users u
        SET 
            reputation = GREATEST(0, reputation - 20),
            cooldown_until = now() + interval '24 hours'
        FROM updated_stats us
        WHERE u.id = us.user_id;
    """)

    result = await db.execute(query)
    # O rowcount aqui retorna quantas linhas foram afetadas no último update (users)
    processed = result.rowcount 
    
    await db.commit()
    return {"processed_no_shows": processed}
