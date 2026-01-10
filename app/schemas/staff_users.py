from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, EmailStr, Field

StaffRole = Literal["INTERNAL_ADMIN", "CLIENT_ADMIN", "CLIENT_STAFF"]

class StaffUserCreateRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=6, max_length=200)
    role: StaffRole = "CLIENT_STAFF"
    name: str | None = Field(default=None, max_length=120)

class StaffUserUpdateRequest(BaseModel):
    role: StaffRole | None = None
    is_active: bool | None = None
    name: str | None = Field(default=None, max_length=120)

class StaffUserResponse(BaseModel):
    id: int
    restaurant_id: int
    email: EmailStr
    role: StaffRole
    is_active: bool
    name: str | None = None
    created_at: datetime
    changed_at: datetime
