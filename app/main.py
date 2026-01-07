from fastapi import FastAPI
from app.settings import settings

app = FastAPI(title="MVP Offers")

@app.get("/health")
def health():
    return {"ok": True, "env": settings.ENV}
