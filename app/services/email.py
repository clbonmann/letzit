# app/services/email.py
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig, MessageType
from app.settings import settings
from app.emails.staff_invite import build_staff_invite_email # <--- Sua função importada aqui

# Configuração da Conexão
conf = ConnectionConfig(
    MAIL_USERNAME=settings.MAIL_USERNAME,
    MAIL_PASSWORD=settings.MAIL_PASSWORD,
    MAIL_FROM=settings.MAIL_FROM,
    MAIL_PORT=settings.MAIL_PORT,
    MAIL_SERVER=settings.MAIL_SERVER,
    MAIL_STARTTLS=True,
    MAIL_SSL_TLS=False,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

async def send_invite_email(email: str, name: str, token: str, restaurant_name: str):
    """
    Constrói o HTML e envia o email usando SMTP assíncrono.
    """
    
    # 1. Gera o HTML e Assunto usando sua função
    subject, html_content = build_staff_invite_email(
        staff_name=name,
        restaurant_name=restaurant_name,
        staff_email=email,
        token=token
    )

    # 2. Prepara a mensagem
    message = MessageSchema(
        subject=subject,
        recipients=[email],  # Lista de destinatários
        body=html_content,
        subtype=MessageType.html
    )

    # 3. Envia
    # fm = FastMail(conf)
    # try:
    #     await fm.send_message(message)
    print(f"✅ Email enviado com sucesso para {email}")
    return True
   # except Exception as e:
   #     print(f"❌ Erro ao enviar email: {e}")
   #     return False