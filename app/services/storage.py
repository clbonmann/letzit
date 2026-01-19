import cloudinary
import cloudinary.uploader
from fastapi import UploadFile, HTTPException
from app.settings import settings

# Configuração Inicial
cloudinary.config( 
  cloud_name = settings.CLOUDINARY_CLOUD_NAME, 
  api_key = settings.CLOUDINARY_API_KEY, 
  api_secret = settings.CLOUDINARY_API_SECRET,
  secure = True
)

ALLOWED_EXTENSIONS = {"image/jpeg", "image/png", "image/webp", "image/jpg"}

# ALTERAÇÃO: Adicionado parametro opcional 'transformation'
def upload_image(file: UploadFile, folder: str, transformation: dict = None) -> str:
    """
    Envia para o Cloudinary e retorna a URL segura (https).
    Aceita dicionário de transformação (crop, resize, etc).
    """
    
    # 1. Validação simples
    if file.content_type not in ALLOWED_EXTENSIONS:
        raise HTTPException(400, "Formato inválido. Use JPG ou PNG.")

    try:
        # 2. Upload Mágico
        response = cloudinary.uploader.upload(
            file.file,
            folder=folder, 
            resource_type="image",
            # AQUI ESTÁ A MÁGICA: Repassa as regras de corte para o Cloudinary
            transformation=transformation 
        )
        
        # 3. Retorna a URL otimizada
        return response.get("secure_url")

    except Exception as e:
        print(f"Erro no Cloudinary: {e}")
        raise HTTPException(500, "Falha no upload da imagem.")