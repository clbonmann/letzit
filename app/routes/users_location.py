from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.deps import get_current_user_id  # seu stub/header X-User-Id

router = APIRouter(prefix="/users/me", tags=["users"])

class UpdateLocationRequest(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy_m: int | None = Field(default=None, ge=0, le=5000)

@router.post("/location")
async def update_location(
    payload: UpdateLocationRequest,
    db: AsyncSession = Depends(get_db_session),
    user_id: int = Depends(get_current_user_id),
):
    now = datetime.now(timezone.utc)
    await db.execute(
        text("""
            UPDATE users
            SET geog = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                last_loc_at = :now,
                loc_accuracy_m = :acc
            WHERE id = :uid
        """),
        {"lng": payload.lng, "lat": payload.lat, "now": now, "acc": payload.accuracy_m, "uid": user_id},
    )
    await db.commit()
    return {"ok": True, "user_id": user_id, "last_loc_at": now}
