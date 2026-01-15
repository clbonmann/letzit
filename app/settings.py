import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# --- FORÇA O CARREGAMENTO DO .ENV ---
# Isso garante que o Python leia o arquivo .env da raiz
load_dotenv()

class Settings(BaseSettings):
    # Configuração para ler .env automaticamente também
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

    # Infra (Obrigatórios - O erro estava aqui)
    DATABASE_URL="postgresql://postgres:GdEb3ccAfgGabgC4g1b41GDGCE4AcDC6@centerbeam.proxy.rlwy.net:51248/railway"
    REDIS_URL="redis://localhost:6379"

    # Celery
    CELERY_BROKER_URL: str | None = None
    CELERY_RESULT_BACKEND: str | None = None

    # Authentication
    JWT_SECRET:str = "segredo_temporario_desenvolvimento_123"
    JWT_EXPIRES_MIN: int = 60 * 24  # 24 horas
    JWT_ALG: str = "HS256"

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: Optional[str] = None
    CLOUDINARY_API_KEY: Optional[str] = None
    CLOUDINARY_API_SECRET: Optional[str] = None

    # Resend
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM: Optional[str] = None
    STAFF_ACTIVATION_BASE_URL: Optional[str] = None

    @property
    def celery_broker(self) -> str:
        return self.CELERY_BROKER_URL or self.REDIS_URL

    @property
    def celery_backend(self) -> str:
        return self.CELERY_RESULT_BACKEND or self.REDIS_URL

settings = Settings()