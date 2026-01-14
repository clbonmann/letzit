from __future__ import annotations

import httpx
from app.settings import settings

RESEND_BASE_URL = "https://api.resend.com"


async def resend_send_email(*, to: str, subject: str, html: str) -> None:
    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": settings.RESEND_FROM,
        "to": [to],
        "subject": subject,
        "html": html,
    }

    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(f"{RESEND_BASE_URL}/emails", json=payload, headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"Resend error: {r.status_code} {r.text}")
