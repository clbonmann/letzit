from datetime import datetime
from pydantic import BaseModel
from uuid import UUID


class AcceptOfferResponse(BaseModel):
    status: str  # ACCEPTED | SOLD_OUT | NOT_ELIGIBLE | CLOSED | COOLDOWN | BLOCKED
    offer_id: int
    user_id: int
    expires_at: datetime | None = None
    qr_token: UUID | None = None
    accepted_count: int | None = None
    accept_limit: int | None = None

