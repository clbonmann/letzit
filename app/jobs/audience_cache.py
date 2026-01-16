from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# radii fixos (km)
RADII_KM = [1, 2, 3, 5, 7, 10, 20, 30, 50]

AUDIENCE_SQL = text("""
WITH r AS (
  SELECT geog
  FROM restaurants
  WHERE id = :rid
),
u AS (
  SELECT geog
  FROM clients
  WHERE geog IS NOT NULL
    AND last_loc_at > now() - make_interval(mins => :mins)
)
SELECT
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r),  1000))::int AS km1,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r),  2000))::int AS km2,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r),  3000))::int AS km3,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r),  5000))::int AS km5,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r),  7000))::int AS km7,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r), 10000))::int AS km10,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r), 20000))::int AS km20,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r), 30000))::int AS km30,
  COUNT(*) FILTER (WHERE ST_DWithin(u.geog, (SELECT geog FROM r), 50000))::int AS km50
FROM u;
""")

UPSERT_CACHE_SQL = text("""
INSERT INTO restaurant_audience_cache (restaurant_id, active_minutes, counts_by_radius, computed_at)
VALUES (:rid, :mins, :counts::jsonb, :computed_at)
ON CONFLICT (restaurant_id)
DO UPDATE SET
  active_minutes = EXCLUDED.active_minutes,
  counts_by_radius = EXCLUDED.counts_by_radius,
  computed_at = EXCLUDED.computed_at;
""")

async def refresh_restaurant_audience_cache(
    db: AsyncSession,
    restaurant_id: int,
    active_minutes: int = 30,
) -> dict:
    # valida restaurante + geog
    rest = (await db.execute(
        text("SELECT id, geog FROM restaurants WHERE id = :rid"),
        {"rid": int(restaurant_id)},
    )).mappings().first()
    if not rest:
        raise ValueError("restaurant not found")
    if rest["geog"] is None:
        raise ValueError("restaurant geog is NULL")

    row = (await db.execute(
        AUDIENCE_SQL,
        {"rid": int(restaurant_id), "mins": int(active_minutes)},
    )).mappings().first()

    counts = {
        "1": int(row["km1"]),
        "2": int(row["km2"]),
        "3": int(row["km3"]),
        "5": int(row["km5"]),
        "7": int(row["km7"]),
        "10": int(row["km10"]),
        "20": int(row["km20"]),
        "30": int(row["km30"]),
        "50": int(row["km50"]),
    }

    now = datetime.now(timezone.utc)

    await db.execute(
        UPSERT_CACHE_SQL,
        {"rid": int(restaurant_id), "mins": int(active_minutes), "counts": str(counts).replace("'", '"'), "computed_at": now},
    )
    await db.commit()

    return {"restaurant_id": int(restaurant_id), "active_minutes": int(active_minutes), "counts_by_radius": counts, "computed_at": now.isoformat()}
