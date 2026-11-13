from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

TrainerStatus = Literal["active", "inactive"]
SessionStatus = Literal["scheduled", "cancelled"]

MAX_BLOCK = timedelta(hours=12)
MIN_SESSION = timedelta(minutes=30)
MAX_SESSION = timedelta(minutes=120)


class TimeRange(BaseModel):

    starts_at: datetime
    ends_at: datetime

    @field_validator("starts_at", "ends_at")
    @classmethod
    def must_be_local_time(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            raise ValueError("use local club time without timezone")
        return value

    @model_validator(mode="after")
    def check_order(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class TrainerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    specialization: str = Field(min_length=1, max_length=50)


class Trainer(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    specialization: str
    status: TrainerStatus


class TrainerStatusUpdate(BaseModel):
    status: TrainerStatus


class AvailabilityCreate(TimeRange):
    @model_validator(mode="after")
    def check_length(self):
        if self.ends_at - self.starts_at > MAX_BLOCK:
            raise ValueError("availability block cannot be longer than 12 hours")
        return self


class Availability(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trainer_id: str
    starts_at: datetime
    ends_at: datetime


class SessionCreate(TimeRange):
    trainer_id: str = Field(min_length=1, max_length=16)
    membership_id: str = Field(pattern=r"^M-\d{3,}$")

    @model_validator(mode="after")
    def check_duration(self):
        if not MIN_SESSION <= self.ends_at - self.starts_at <= MAX_SESSION:
            raise ValueError("session must last from 30 to 120 minutes")
        return self


class Session(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    trainer_id: str
    membership_id: str
    starts_at: datetime
    ends_at: datetime
    status: SessionStatus
