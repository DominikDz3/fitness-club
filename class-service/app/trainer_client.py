from urllib.error import HTTPError, URLError

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

TRAINER_SERVICE = "TRAINER-SERVICE"
TIMEOUT_SECONDS = 3


class TrainerInfo(BaseModel):
    id: str
    status: str


async def ensure_trainer_can_lead_class(eureka_client, trainer_id: str) -> None:
    try:
        body = await eureka_client.do_service(
            TRAINER_SERVICE,
            f"/trainers/{trainer_id}",
            return_type="json",
            timeout=TIMEOUT_SECONDS,
        )
    except HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(status_code=404, detail="Trainer not found") from exc
        raise HTTPException(status_code=502, detail="Trainer Service returned an HTTP error") from exc
    except (URLError, TimeoutError) as exc:
        raise HTTPException(status_code=503, detail="Trainer Service is unavailable") from exc

    try:
        trainer = TrainerInfo.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="Trainer Service returned an invalid response") from exc

    if trainer.status != "active":
        raise HTTPException(status_code=409, detail=f"Trainer is not active (status '{trainer.status}')")