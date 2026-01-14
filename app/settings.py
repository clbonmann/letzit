from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

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
    JWT_EXPIRES_MIN: int = 60 * 24  # 24 horas
    JWT_ALG: str = "HS256"

    #Cloudinary
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    #Resend
    RESEND_API_KEY: str
    RESEND_FROM: str
    STAFF_ACTIVATION_BASE_URL: str  # ex: https://letzit.app/staff-activate

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

settings = Settings()
