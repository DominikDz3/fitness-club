from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ClassStatus = Literal["scheduled", "finished", "cancelled"]

MIN_DURATION = timedelta(minutes=30)
MAX_DURATION = timedelta(minutes=120)


class GroupClassCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    trainer_id: str = Field(pattern=r"^T-\d{3,}$")
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(ge=1, le=50)

    @field_validator("starts_at", "ends_at")
    @classmethod
    def must_be_local_time(cls, value: datetime) -> datetime:
        if value.tzinfo is not None:
            raise ValueError("use local club time without timezone")
        return value

    @model_validator(mode="after")
    def check_times(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if not MIN_DURATION <= self.ends_at - self.starts_at <= MAX_DURATION:
            raise ValueError("class must last from 30 to 120 minutes")
        return self


class GroupClass(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    trainer_id: str
    starts_at: datetime
    ends_at: datetime
    capacity: int
    status: ClassStatus