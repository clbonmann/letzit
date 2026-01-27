import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Tenta carregar o .env localmente (no Railway isso é ignorado, o que é bom)
load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8", 
        extra="ignore"
    )

    # Ambiente
    ENV: str = "prod"
    DEBUG: bool = False

    # App
    APP_NAME: str = "LetzIT"

    # Infra (Aqui estava o erro: Use ':' e não '=')
    DATABASE_URL: Optional[str] = None
    REDIS_URL: Optional[str] = None

    # Authentication
    JWT_SECRET: str | None = None
    JWT_EXPIRES_MIN: int = 60 * 24
    JWT_ALG: str = "HS256"

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # Resend
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM: Optional[str] = None
    STAFF_ACTIVATION_BASE_URL: Optional[str] = None

    # Celery
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL
    

    STAFF_ACTIVATION_BASE_URL: str = "https://letzit.com.br/activate"

    # Configurações de Email
    MAIL_USERNAME: str = "letzitbr@gmail.com"
    MAIL_PASSWORD: str = "cgjf hnev pgkx caua" # Se usar Gmail, gere uma "App Password"
    MAIL_FROM: str = "noreply@letzit.com"
    MAIL_PORT: int = 587
    MAIL_SERVER: str = "smtp.gmail.com"
    MAIL_FROM_NAME: str = "LetzIT Team"
    # MAIL_TLS: bool = True (em versões mais novas do pydantic/fastapi-mail a config mudou um pouco, veja abaixo)

settings = Settings()
