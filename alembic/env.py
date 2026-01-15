import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Importa suas settings (que já leem o .env) e seus modelos
from app.settings import settings
from app.models import Base 

config = context.config

# Configuração de Log padrão do Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# --- AJUSTE 1: Pega a URL direto do Settings (mais seguro) ---
def get_database_url() -> str:
    # O settings já leu o .env, então pegamos de lá
    url = str(settings.DATABASE_URL)
    
    # Garante o driver async
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    
    return url

# --- AJUSTE 2: Filtro para ignorar tabelas do PostGIS ---
def include_object(object, name, type_, reflected, compare_to):
    """
    Diz ao Alembic para IGNORAR a tabela interna do PostGIS.
    Assim ele para de tentar dar 'drop_table("spatial_ref_sys")'.
    """
    if type_ == "table" and name == "spatial_ref_sys":
        return False
    return True

def run_migrations_offline():
    """Run migrations in 'offline' mode."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object, # <--- Adicionado o filtro aqui
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object, # <--- Adicionado o filtro aqui
        compare_type=True, # Importante para detectar mudanças de tipo (String -> Text, etc)
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    """Run migrations in 'online' mode."""
    
    # Cria a engine usando a URL correta
    connectable = async_engine_from_config(
        {
            "sqlalchemy.url": get_database_url(),
        },
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online_wrapper():
    asyncio.run(run_migrations_online())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online_wrapper()
