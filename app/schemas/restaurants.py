from __future__ import annotations
from pydantic import BaseModel, Field

class RestaurantUpdateRequest(BaseModel):
    id: int
    name: str | None = Field(default=None, max_length=120)

    cnpj: str | None = Field(default=None, description="14 digits, only numbers")

    address_street: str | None = None
    address_number: str | None = None
    address_district: str | None = None
    address_city: str | None = None
    address_state: str | None = Field(default=None, max_length=2)
    address_zip: str | None = None
    address_country: str | None = Field(default="BR", max_length=2)

    logo_url: str | None = None  # se você quiser permitir set manual (por admin)

class RestaurantResponse(BaseModel):
    id: int
    name: str

    cnpj: str | None = None

    address_street: str | None = None
    address_number: str | None = None
    address_district: str | None = None
    address_city: str | None = None
    address_state: str | None = None
    address_zip: str | None = None
    address_country: str | None = None

    logo_url: str | None = None
