from __future__ import annotations
from app.settings import settings


def build_staff_invite_email(*, staff_name: str, store_name: str, staff_email: str, token: str) -> tuple[str, str]:
    link = f"{settings.STAFF_ACTIVATION_BASE_URL}?token={token}"
    subject = f"Activate your LetzIT Staff Account ({store_name})"

    html = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.4">
      <h2><b>{staff_name}</b>, you're invited to LetzIT</h2>
      <p>You have been added as a staff member for <b>{store_name}</b>.</p>
      <p>This email is for your use only.</p>
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
