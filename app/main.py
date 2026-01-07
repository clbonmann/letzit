from fastapi import FastAPI
from app.settings import settings
from app.db import db_healthcheck

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

@app.get("/health")
async def health():
    # Liveness: só diz que a API está de pé
    return {"ok": True, "app": settings.APP_NAME, "env": settings.ENV}

@app.get("/ready")
async def ready():
    # Readiness: checa dependências (DB)
    db_ok = await db_healthcheck()
    if not db_ok:
        # aqui você pode retornar 503 explicitamente
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail="DB not ready")
    return {"ok": True, "db": True}
