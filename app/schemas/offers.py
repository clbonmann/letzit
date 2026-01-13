from datetime import datetime
from pydantic import BaseModel
from uuid import UUID


class AcceptOfferResponse(BaseModel):
    status: str  # ACCEPTED | SOLD_OUT | NOT_ELIGIBLE | CLOSED | COOLDOWN | BLOCKED
    offer_id: int
    user_id: Optional[int] = None
    expires_at: Optional[datetime] = None
    qr_token: Optional[UUID] = None
    accepted_count: Optional[int] = 0
    accept_limit: Optional[int] = 0
