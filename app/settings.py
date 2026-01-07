from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENV: str = "prod"

    DATABASE_URL: str  # ex: postgresql+asyncpg://...
    REDIS_URL: str     # ex: redis://...

    # Celery
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

settings = Settings()
