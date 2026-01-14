from __future__ import annotations
from app.settings import settings


def build_staff_invite_email(*, restaurant_name: str, token: str) -> tuple[str, str]:
    link = f"{settings.STAFF_ACTIVATION_BASE_URL}?token={token}"
    subject = f"Activate your LetzIT Staff Account ({restaurant_name})"

    html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.4">
      <h2>You're invited to LetzIT</h2>
      <p>You have been added as a staff member for <b>{restaurant_name}</b>.</p>
      <p>Click below to activate your account and set your password:</p>
      <p>
        <a href="{link}" style="display:inline-block;padding:12px 16px;background:#111827;color:#fff;text-decoration:none;border-radius:8px;">
          Activate Account
        </a>
      </p>
      <p style="color:#6b7280;font-size:12px;">This link expires in 24 hours.</p>
      <p><a href="{link}">{link}</a></p>
    </div>
    """
    return subject, html
