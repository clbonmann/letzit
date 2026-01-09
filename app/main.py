from fastapi import FastAPI
from app.settings import settings

# IMPORTS CORRETOS DOS ROUTERS
from app.routes.offers import router as offers_router
from app.routes.admin import router as admin_router
from app.routes.redeem import router as redeem_router
from app.routes.staff_auth import router as staff_auth_router
from app.routes.admin_jobs import router as admin_jobs_router
from app.routes.users_location import router as users_location_router
from app.routes.staff_offers_quote import router as staff_offers_quote_router
from app.routes.staff_offers_create import router as staff_offers_create_router
from app.routes.home import router as home_router
from app.routes.offers_public import router as offers_public_router
from app.routes.staff_jobs import router as staff_jobs_router
from app.routes.staff_offers_list import router as staff_offers_list_router
from app.routes.staff_offers_eligible_users import router as staff_offers_eligible_users_router

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
app.include_router(users_location_router)
app.include_router(staff_offers_quote_router)
app.include_router(staff_offers_create_router)
app.include_router(home_router)
app.include_router(offers_public_router)
app.include_router(staff_jobs_router)
app.include_router(staff_offers_list_router)
app.include_router(staff_offers_eligible_users_router)

@app.get("/health")
def health():
    return "ok"

@app.get("/ready")
def ready():
    return {"ok": True}
