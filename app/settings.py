from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Ambiente
    ENV: str = "prod"
    DEBUG: bool = False

    # App
    APP_NAME: str = "LetzIT"

    # Infra
    DATABASE_URL: str
    REDIS_URL: str

    # Celery
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    #Authentication
    JWT_SECRET: str | None = None

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

settings = Settings()
