from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps_staff import get_current_staff
import app.tasks.no_show as no_show

router = APIRouter(prefix="/staff/jobs", tags=["staff-jobs"])

@router.post("/no-show")
async def job_no_show(
    cooldown_hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff),
):
    # se você quiser restringir a “admin staff”, checa staff["role"] aqui
    try:
        return await no_show.run_no_show_job(db, cooldown_hours=cooldown_hours)
    except Exception as e:
        raise HTTPException(500, f"job failed: {e}")
