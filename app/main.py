from fastapi import FastAPI
from app.db import db_healthcheck

app = FastAPI(title="LetzIT API")

@app.get("/health")
async def health():
    db_ok = await db_healthcheck()
    return {"ok": True, "db": db_ok}

