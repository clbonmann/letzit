from fastapi import HTTPException

def require_admin(staff: dict) -> None:
    role = staff.get("role")
    if role not in ("STORE_ADMIN", "INTERNAL_ADMIN"):
        raise HTTPException(status_code=403, detail="Admin role required")

def require_internal_admin(staff: dict) -> None:
    if staff.get("role") != "INTERNAL_ADMIN":
        raise HTTPException(status_code=403, detail="Internal admin required")
