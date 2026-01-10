from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.settings import settings

RADIUS_COUNTS_SQL = text("""
WITH r AS (
  SELECT geog
  FROM restaurants
  WHERE id = :rid
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
FROM users u
WHERE u.geog IS NOT NULL
  AND u.last_loc_at > now() - interval '15 minutes';
""")

UPSERT_SQL = text("""
INSERT INTO restaurant_audience_cache (restaurant_id, active_minutes, counts_by_radius, computed_at)
VALUES (:rid, 15, :counts::jsonb, :computed_at)
ON CONFLICT (restaurant_id)
DO UPDATE SET
  active_minutes = 15,
  counts_by_radius = EXCLUDED.counts_by_radius,
  computed_at = EXCLUDED.computed_at;
""")

async def run_once() -> None:
  def to_asyncpg(url: str) -> str:
    # Railway às vezes fornece "postgres://"
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    # força asyncpg se vier sem driver
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    # se alguém colocou "postgres://user:pass@..." também cai aqui
    if url.startswith("postgresql+psycopg2://"):
        url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://", 1)
    return url
    db_url = to_asyncpg(settings.DATABASE_URL)
    engine = create_async_engine(db_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)

    async with Session() as db:
        # pega restaurantes com geog
        restaurants = (await db.execute(
            text("SELECT id FROM restaurants WHERE geog IS NOT NULL")
        )).scalars().all()

        updated = 0
        for rid in restaurants:
            row = (await db.execute(RADIUS_COUNTS_SQL, {"rid": int(rid)})).mappings().first()
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
            await db.execute(
                UPSERT_SQL,
                {"rid": int(rid), "counts": json.dumps(counts), "computed_at": now},
            )
            updated += 1

        await db.commit()

    await engine.dispose()
    print(f"[audience-cache] computed_at={now.isoformat()} restaurants_updated={updated}")

def main() -> None:
    asyncio.run(run_once())

if __name__ == "__main__":
    main()
