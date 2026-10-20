from datetime import date, timedelta
from itertools import count
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

SERVICE_NAME = "membership-service"

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
    id: str
    member_id: str
    type: MembershipType
    valid_from: date
    valid_to: date
    status: MembershipStatus
    suspended_until: date | None = None


class SuspendRequest(BaseModel):
    days: int = Field(ge=1, le=30)


def seed_data() -> dict[str, Membership]:
    return {
        "M-001": Membership(
            id="M-001", member_id="U-100", type="open",
            valid_from=date(2026, 10, 1), valid_to=date(2026, 12, 31),
            status="active",
        ),
        "M-002": Membership(
            id="M-002", member_id="U-200", type="morning",
            valid_from=date(2026, 9, 1), valid_to=date(2026, 11, 30),
            status="suspended", suspended_until=date(2026, 10, 25),
        ),
    }


def create_app() -> FastAPI:
    app = FastAPI(title="Membership Service")
    store = seed_data()
    next_id = count(len(store) + 1)

    def get_or_404(membership_id: str) -> Membership:
        membership = store.get(membership_id)
        if membership is None:
            raise HTTPException(status_code=404, detail="Nie znaleziono karnetu")
        return membership

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SERVICE_NAME}

    @app.get("/memberships", response_model=list[Membership])
    def list_memberships():
        return list(store.values())

    @app.get("/memberships/{membership_id}", response_model=Membership)
    def get_membership(membership_id: str):
        return get_or_404(membership_id)

    @app.post("/memberships", response_model=Membership, status_code=201)
    def create_membership(payload: MembershipCreate):
        has_current = any(
            m.member_id == payload.member_id and m.status in ("active", "suspended")
            for m in store.values()
        )
        if has_current:
            raise HTTPException(status_code=409, detail="Członek ma już karnet")

        membership_id = f"M-{next(next_id):03d}"
        membership = Membership(id=membership_id, status="active", **payload.model_dump())
        store[membership_id] = membership
        return membership

    @app.patch("/memberships/{membership_id}/suspend", response_model=Membership)
    def suspend_membership(membership_id: str, payload: SuspendRequest):
        membership = get_or_404(membership_id)
        if membership.status != "active":
            raise HTTPException(status_code=409, detail=f"Nie można zawiesić karnetu o statusie: '{membership.status}'")

        updated = membership.model_copy(update={
            "status": "suspended",
            "suspended_until": date.today() + timedelta(days=payload.days),
            "valid_to": membership.valid_to + timedelta(days=payload.days),
        })
        store[membership_id] = updated
        return updated

    @app.patch("/memberships/{membership_id}/resume", response_model=Membership)
    def resume_membership(membership_id: str):
        membership = get_or_404(membership_id)
        if membership.status != "suspended":
            raise HTTPException(status_code=409, detail=f"Nie można wznowić karnetu o statusie: '{membership.status}'")

        updated = membership.model_copy(update={"status": "active", "suspended_until": None})
        store[membership_id] = updated
        return updated

    return app


app = create_app()