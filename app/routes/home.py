from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session

router = APIRouter(prefix="/home", tags=["home"])


@router.get("/featured")
async def home_featured(city: str, db: AsyncSession = Depends(get_db_session)):
    city_norm = city.strip().lower().replace(" ", "_").replace("-", "_")

    rows = (await db.execute(
        text("""
            SELECT
                o.id,
                o.restaurant_id,
                o.title,
                o.message,
                o.price_cents,
                o.radius_km,
                o.created_at,
                o.end_offer
            FROM offers o
            JOIN restaurants r ON r.id = o.restaurant_id
            WHERE o.placement = 'CITY_HOME'
              AND o.end_offer > now()
              AND COALESCE(o.status, 'ACTIVE') = 'ACTIVE'
              AND COALESCE(r.city, '') = :city
            ORDER BY o.created_at DESC
            LIMIT 5
        """),
        {"city": city_norm},
    )).mappings().all()

    return {"city": city_norm, "items": rows}
