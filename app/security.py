import hashlib
from datetime import datetime, timedelta, timezone

from passlib.context import CryptContext
from jose import jwt

from app.settings import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def _prehash(password: str) -> str:
    """
    Pré-hash com SHA-256 para evitar limite de 72 bytes do bcrypt
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_password(password: str) -> str:
    pre = _prehash(password)
    print("hash_password lengths:", len(password.encode("utf-8")), len(pre.encode("utf-8")))
    return pwd_context.hash(pre)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(_prehash(password), password_hash)


def create_access_token(subject: str, extra: dict | None = None) -> str:
    if not settings.JWT_SECRET:
        raise RuntimeError("JWT_SECRET not configured")

    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRES_MIN)).timestamp()),
    }
    if extra:
        payload.update(extra)

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALG)
