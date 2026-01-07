from datetime import datetime
from pydantic import BaseModel
from uuid import UUID


class RedeemVerifyRequest(BaseModel):
    qr_token: UUID


class RedeemVerifyResponse(BaseModel):
    status: str  # REDEEMED | INVALID | EXPIRED | ALREADY_REDEEMED | NOT_ACCEPTED
    offer_id: int
    claim_id: int | None = None
    user_id: int | None = None
    redeemed_at: datetime | None = None
