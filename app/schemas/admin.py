from datetime import datetime
from pydantic import BaseModel, EmailStr, Field

class CreateUserRequest(BaseModel):
    phone_e164: str = Field(..., examples=["+5511999999999"])
    level: int = 1
    reputation: int = 100

class CreateUserResponse(BaseModel):
    id: int
    phone_e164: str

class CreateRestaurantRequest(BaseModel):
    name: str
    cnpj: str

class CreateRestaurantResponse(BaseModel):
    id: int
    name: str

class CreateOfferRequest(BaseModel):
    restaurant_id: int
    title: str
    description: str | None = None
    end_at: datetime
    accept_limit: int = 25
    target_batch_size: int = 50
    max_target_total: int = 300
    accept_ttl_hours: int = 6

class CreateOfferResponse(BaseModel):
    id: int
    status: str
    accept_limit: int
    end_at: datetime

class AddTargetsRequest(BaseModel):
    user_ids: list[int]
    batch_no: int = 1
    state: str = "RELEASED"

class CreateStaffRequest(BaseModel):
    restaurant_id: int
    email: EmailStr
    password: str
    role: str = "CLIENT_ADMIN" # ou "INTERNAL_ADMIN", "CLIENT_STAFF"

