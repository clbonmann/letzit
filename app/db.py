from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from app.settings import settings


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = _normalize_db_url(settings.DATABASE_URL)

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,      # Testa a conexão antes de usar
    pool_recycle=1800,       # Recicla conexões a cada 30min
    pool_size=10,            # Mantém até 10 conexões abertas
    max_overflow=20,        # Permite explodir até 20 se precisar muito
    pool_timeout=30,
    echo=False,  # Deixe False para limpar o log
    connect_args={
        "server_settings": {
            "application_name": "letzit_app" # Ajuda a identificar no log do banco
        },
        "command_timeout": 60 # Aumenta a tolerância de espera
    }
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


# ✅ Dependency correta para FastAPI
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def db_healthcheck() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
