from datetime import datetime
from pydantic import BaseModel
from uuid import UUID


class RedeemVerifyRequest(BaseModel):
    qr_token: UUID


class RedeemVerifyResponse(BaseModel):
    # VALID | INVALID | EXPIRED | ALREADY_REDEEMED | NOT_ACCEPTED | CANCELLED
    status: str
    offer_id: int
    claim_id: int | None = None
    user_id: int | None = None
    expires_at: datetime | None = None
    redeemed_at: datetime | None = None


class RedeemConsumeResponse(BaseModel):
    # REDEEMED | INVALID | EXPIRED | ALREADY_REDEEMED | CANCELLED | NOT_REDEEMABLE
    status: str
    offer_id: int
    claim_id: int | None = None
    user_id: int | None = None
    redeemed_at: datetime | None = None
