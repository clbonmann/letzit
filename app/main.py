from fastapi import FastAPI
from app.settings import settings

# IMPORTS CORRETOS DOS ROUTERS
from app.routes.admin import router as admin_router
from app.routes.admin_jobs import router as admin_jobs_router
from app.routes.auth_clients import router as auth_clients_router
from app.routes.clients_location import router as clients_location_router
from app.routes.home import router as home_router
from app.routes.offers import router as offers_router
from app.routes.offers_public import router as offers_public_router
from app.routes.redeem import router as redeem_router
from app.routes.restaurant_logo import router as restaurant_logo_router
from app.routes.staff_activate import router as staff_activate_router
from app.routes.staff_activation import router as staff_activation_router
from app.routes.staff_audience_stats import router as staff_audience_router
from app.routes.staff_auth import router as staff_auth_router
from app.routes.staff_debug_accept import router as staff_debug_router
from app.routes.staff_jobs import router as staff_jobs_router
from app.routes.staff_offers_close import router as staff_offers_close_router
from app.routes.staff_offers_create import router as staff_offers_create_router
from app.routes.staff_offers_eligible_users import router as staff_offers_eligible_users_router
from app.routes.staff_offers_list import router as staff_offers_list_router
from app.routes.staff_offers_quote import router as staff_offers_quote_router
from app.routes.staff_offers_repeat import router as staff_offers_repeat_router
from app.routes.staff_offers_update import router as staff_offers_update_router
from app.routes.staff_restaurant import router as staff_restaurant_router
from app.routes.staff_restaurant_registry import router as staff_restaurant_registry_router
from app.routes.staff_stats import router as staff_stats_router
from app.routes.staff_users import router as staff_users_router
from app.routes.staff_users_password import router as staff_users_password_router


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
)

# REGISTRO DOS ROUTERS
app.include_router(admin_jobs_router)
app.include_router(admin_router)
app.include_router(auth_clients_router)
app.include_router(clients_location_router)
app.include_router(home_router)
app.include_router(offers_public_router)
app.include_router(offers_router)
app.include_router(redeem_router)
app.include_router(restaurant_logo_router)
app.include_router(staff_activate_router)
app.include_router(staff_activation_router)
app.include_router(staff_audience_router)
app.include_router(staff_auth_router)
app.include_router(staff_debug_router)
app.include_router(staff_jobs_router)
app.include_router(staff_offers_close_router)
app.include_router(staff_offers_create_router)
app.include_router(staff_offers_eligible_users_router)
app.include_router(staff_offers_list_router)
app.include_router(staff_offers_quote_router)
app.include_router(staff_offers_repeat_router)
app.include_router(staff_offers_update_router)
app.include_router(staff_restaurant_registry_router)
app.include_router(staff_restaurant_router)
app.include_router(staff_stats_router)
app.include_router(staff_users_password_router)
app.include_router(staff_users_router)


@app.get("/health")
def health():
    return "ok"

@app.get("/ready")
def ready():
    return {"ok": True}
