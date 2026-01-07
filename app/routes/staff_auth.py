from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db_session
from app.schemas.staff_auth import StaffLoginRequest, StaffLoginResponse, StaffMeResponse
from app.security import verify_password, create_access_token
from app.deps_staff import get_current_staff

router = APIRouter(prefix="/staff", tags=["staff-auth"])


@router.post("/login", response_model=StaffLoginResponse)
async def staff_login(
    payload: StaffLoginRequest,
    db: AsyncSession = Depends(get_db_session),
) -> StaffLoginResponse:
    staff = (await db.execute(
        text("""
            SELECT id, password_hash, is_active
            FROM restaurant_staff
            WHERE lower(email) = lower(:email)
        """),
        {"email": payload.email},
    )).mappings().first()

    if not staff or not staff["is_active"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not verify_password(payload.password, staff["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=str(staff["id"]))
    return StaffLoginResponse(access_token=token)


@router.get("/me", response_model=StaffMeResponse)
async def staff_me(staff: dict = Depends(get_current_staff)) -> StaffMeResponse:
    return StaffMeResponse(
        id=int(staff["id"]),
        restaurant_id=int(staff["restaurant_id"]),
        email=staff["email"],
        role=staff["role"],
    )
