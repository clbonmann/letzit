import certifi
import os

# --- CORREÇÃO DE SSL PARA WINDOWS ---
# Isso força o sistema a usar o certificado correto instalado pelo pip
os.environ["SSL_CERT_FILE"] = certifi.where()

import resend
from app.settings import settings
from app.emails.staff_invite import build_staff_invite_email

# Configure a chave (adicione RESEND_API_KEY no .env e settings.py)
resend.api_key = settings.RESEND_API_KEY

async def send_invite_email(email: str, name: str, token: str, restaurant_name: str):
    
    subject, html_content = build_staff_invite_email(
        staff_name=name,
        restaurant_name=restaurant_name,
        staff_email=email,
        token=token
    )

    try:
        r = resend.Emails.send({
            "from": "LetzIT Team <nao-responda@letzit.com.br>", # Tem que ser o domínio verificado
            "to": email,
            "subject": subject,
            "html": html_content
        })
        print(f"✅ Email enviado via Resend ID: {r['id']}")
        return True
    except Exception as e:
        print(f"❌ Erro Resend: {e}")
        return False