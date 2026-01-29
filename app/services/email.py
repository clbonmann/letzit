import os
import certifi
import resend
from app.settings import settings
from app.emails.staff_invite import build_staff_invite_email

real_cert_path = certifi.where()
print(f"🔒 Certificado SSL carregado de: {real_cert_path}")

# 2. Força TODAS as variáveis de ambiente que o Python/Requests usam
# O erro acontece porque o 'REQUESTS_CA_BUNDLE' provavelmente está apontando pro lugar errado
os.environ["SSL_CERT_FILE"] = real_cert_path
os.environ["REQUESTS_CA_BUNDLE"] = real_cert_path

# Configure a chave (adicione RESEND_API_KEY no .env e settings.py)
resend.api_key = settings.RESEND_API_KEY

async def send_invite_email(email: str, name: str, token: str, store_name: str):
    
    clean_email = str(email).strip().lower()

    subject, html_content = build_staff_invite_email(
        staff_name=name,
        store_name=store_name,
        staff_email=clean_email,
        token=token
    )
    params: resend.Emails.SendParams = {
        "from": "LetzIT Team <onboard@letzit.com.br>", # Tem que ser o domínio verificado
        "to": [clean_email],
        "subject": subject,
        "html": html_content
    }

    try:
        email = resend.Emails.send(params)
        print(f"✅ Email enviado via Resend ID: {email['id']}")
        return True
    except Exception as e:
        print(f"❌ Erro Resend: {e}")
        return False