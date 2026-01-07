from fastapi import FastAPI
from app.settings import settings

# IMPORTS CORRETOS DOS ROUTERS
from app.routes.offers import router as offers_router
from app.routes.admin import router as admin_router
from app.routes.redeem import router as redeem_router
from app.routes.staff_auth import router as staff_auth_router
from app.routes.admin_jobs import router as admin_jobs_router

app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
)

# REGISTRO DOS ROUTERS
app.include_router(offers_router)
app.include_router(admin_router)
app.include_router(redeem_router)
app.include_router(staff_auth_router)
app.include_router(admin_jobs_router)


@app.get("/health")
def health():
    return "ok"

@app.get("/ready")
def ready():
    return {"ok": True}
