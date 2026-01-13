from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db_session
from app.deps_staff import get_current_staff
from app.services.storage import upload_image # <--- Nosso novo serviço Cloudinary

router = APIRouter(prefix="/restaurants", tags=["restaurants"])

@router.post("/logo")
async def upload_restaurant_logo(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
    staff: dict = Depends(get_current_staff)
):
    restaurant_id = int(staff["restaurant_id"])

    # 1. Faz o upload (Gratuito no Cloudinary)
    # Vai salvar na pasta "restaurants/id_do_restaurante"
    url = upload_image(file, folder=f"restaurants/{restaurant_id}")

    # 2. Salva SOMENTE A URL no banco
    await db.execute(
        text("UPDATE restaurants SET logo_url = :url, updated_at = NOW() WHERE id = :rid"),
        {"url": url, "rid": restaurant_id}
    )
    await db.commit()

    return {
        "message": "Logo atualizado!",
        "logo_url": url
    }
