from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MembershipType = Literal["open", "morning", "gym_only"]
MembershipStatus = Literal["active", "suspended", "expired"]


class MembershipCreate(BaseModel):
    member_id: str = Field(min_length=1, max_length=50)
    type: MembershipType
    valid_from: date
    valid_to: date

    @model_validator(mode="after")
    def check_dates(self):
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self


class Membership(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    member_id: str
    type: MembershipType
    valid_from: date
    valid_to: date
    status: MembershipStatus
    suspended_until: date | None = None


class SuspendRequest(BaseModel):
    days: int = Field(ge=1, le=30)
