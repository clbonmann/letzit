from fastapi import FastAPI
from app.settings import settings
from app.db import db_healthcheck

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
)

@app.get("/health")
async def health():
    db_ok = await db_healthcheck()
    return {
        "ok": True,
        "app": settings.APP_NAME,
        "env": settings.ENV,
        "db": db_ok
    }


