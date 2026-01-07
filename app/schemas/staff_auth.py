from pydantic import BaseModel, EmailStr


class StaffLoginRequest(BaseModel):
    email: EmailStr
    password: str


class StaffLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StaffMeResponse(BaseModel):
    id: int
    restaurant_id: int
    email: EmailStr
    role: str
