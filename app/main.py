from fastapi import FastAPI

# 1. Client Routes (App Mobile)
from app.routes import client_auth, client_feed, client_profile

# 2. Staff Routes (Painel Restaurante)
from app.routes import (
    staff_auth, 
    staff_restaurant, 
    staff_offers, 
    staff_team, 
    staff_pos, 
    staff_stats
)

# 3. Admin Routes (Backoffice)
from app.routes import admin, admin_jobs

app = FastAPI(title="LetzIT API")

# --- Include Routers ---

# Client
app.include_router(client_auth.router)
app.include_router(client_feed.router)
app.include_router(client_profile.router)

# Staff
app.include_router(staff_auth.router)
app.include_router(staff_restaurant.router)
app.include_router(staff_offers.router)
app.include_router(staff_team.router)
app.include_router(staff_pos.router)
app.include_router(staff_stats.router)

# Admin
app.include_router(admin.router)
app.include_router(admin_jobs.router)

@app.get("/health", tags=["system"])
async def health_check():
    """Endpoint simples para verificar se a API está no ar."""
    return {"status": "ok", "version": "2.0.0"}
