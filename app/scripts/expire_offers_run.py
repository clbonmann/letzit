from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.settings import settings


def to_asyncpg(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


EXPIRE_SQL = text("""
UPDATE offers
SET status = 'EXPIRED',
    status_reason = 'AUTO_EXPIRED',
    status_changed_by_staff_id = NULL
WHERE end_at IS NOT NULL
  AND end_at <= now()
  AND status IN ('CREATED', 'ACTIVE', 'PAUSED');
""")


async def run_once() -> None:
    db_url = to_asyncpg(settings.DATABASE_URL)
    engine = create_async_engine(db_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(timezone.utc)

    async with Session() as db:
        res = await db.execute(EXPIRE_SQL)
        await db.commit()
        # rowcount funciona na maioria dos casos com SQLAlchemy 2.0
        print(f"[expire-offers] at={now.isoformat()} updated={getattr(res, 'rowcount', None)}")

    await engine.dispose()


def main() -> None:
    asyncio.run(run_once())


if __name__ == "__main__":
    main()
