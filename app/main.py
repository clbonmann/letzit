from fastapi import FastAPI
from app.settings import settings
from app.db import db_healthcheck
from app.routes.admin import router as admin_router

app = FastAPI(title=settings.APP_NAME, debug=settings.DEBUG)

app.include_router(admin_router)
app.include_router(offers_router)

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
