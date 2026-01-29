from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer

# 1. Client Routes (App Mobile)
from app.routes import client_auth, client_feed, client_profile

# 2. Staff Routes (Painel Store)
from app.routes import (
    staff_auth, 
    staff_store, 
    staff_offers, 
    staff_team, 
    staff_pos, 
    staff_stats, 
    staff_packages
)

# 3. Admin Routes
from app.routes import admin, admin_jobs

app = FastAPI(title="LetzIT API")

# CORS Middleware Configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, troque "*" pela URL do seu frontend (ex: https://meusite.com)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- INCLUSÃO DAS ROTAS ---

# Client
app.include_router(client_auth.router)
app.include_router(client_feed.router)
app.include_router(client_profile.router)

# Staff
app.include_router(staff_auth.router)
app.include_router(staff_store.router)
app.include_router(staff_offers.router)
app.include_router(staff_team.router)
app.include_router(staff_pos.router)
app.include_router(staff_stats.router)
app.include_router(staff_packages.router)

# Admin
app.include_router(admin.router)
app.include_router(admin_jobs.router)

@app.get("/health", tags=["system"])
async def health_check():
    """Endpoint simples para verificar se a API está no ar."""
    return {"status": "ok", "version": "2.0.0"}