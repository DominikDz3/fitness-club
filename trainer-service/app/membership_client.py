from datetime import date
from urllib.error import HTTPError, URLError

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from app.models import SessionCreate

MEMBERSHIP_SERVICE = "MEMBERSHIP-SERVICE"
TIMEOUT_SECONDS = 3


class MembershipInfo(BaseModel):
    """Tylko te pola odpowiedzi Membership Service, których potrzebuje Trainer Service."""

    id: str
    status: str
    valid_from: date
    valid_to: date


async def ensure_membership_allows_session(eureka_client, payload: SessionCreate) -> None:
    try:
        body = await eureka_client.do_service(
            MEMBERSHIP_SERVICE,
            f"/memberships/{payload.membership_id}",
            return_type="json",
            timeout=TIMEOUT_SECONDS,
        )
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=404, detail="Membership not found") from exc
        raise HTTPException(status_code=502, detail="Membership Service returned an HTTP error") from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Membership Service is unavailable") from exc

    try:
        membership = MembershipInfo.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="Membership Service returned an invalid response") from exc

    if membership.status != "active":
        raise HTTPException(status_code=409, detail=f"Membership is not active (status '{membership.status}')")
    if not membership.valid_from <= payload.starts_at.date() <= membership.valid_to:
        raise HTTPException(status_code=409, detail="Membership is not valid on the session date")