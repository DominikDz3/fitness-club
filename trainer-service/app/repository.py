from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db_models import AvailabilityRow, SessionRow, TrainerRow
from app.models import (
    Availability, AvailabilityCreate, Session, SessionCreate, Trainer, TrainerCreate,
)

SEED_TRAINERS = [
    dict(id="T-001", name="Anna Nowak", specialization="strength", status="active"),
    dict(id="T-002", name="Piotr Kowalski", specialization="yoga", status="inactive"),
]
SEED_AVAILABILITY = [
    dict(id="A-001", trainer_id="T-001",
         starts_at=datetime(2026, 11, 16, 8, 0), ends_at=datetime(2026, 11, 16, 12, 0)),
    dict(id="A-002", trainer_id="T-001",
         starts_at=datetime(2026, 11, 16, 16, 0), ends_at=datetime(2026, 11, 16, 20, 0)),
]
SEED_SESSIONS = [
    dict(id="S-001", trainer_id="T-001", membership_id="M-001",
         starts_at=datetime(2026, 11, 16, 9, 0), ends_at=datetime(2026, 11, 16, 10, 0),
         status="scheduled"),
]


class NotFound(LookupError):
    """Brak zasobu -> 404."""


class Conflict(ValueError):
    """Poprawne dane sprzeczne z aktualnym stanem -> 409."""


def overlaps(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and start_b < end_a


class TrainerRepository:

    def __init__(self, sessions):
        self.sessions = sessions

    def seed(self):
        with self.sessions.begin() as db:
            if db.scalar(select(func.count()).select_from(TrainerRow)) == 0:
                db.add_all([TrainerRow(**data) for data in SEED_TRAINERS])
                db.flush()
                db.add_all([AvailabilityRow(**data) for data in SEED_AVAILABILITY])
                db.add_all([SessionRow(**data) for data in SEED_SESSIONS])

    def list_trainers(self) -> list[Trainer]:
        with self.sessions() as db:
            rows = db.scalars(select(TrainerRow).order_by(TrainerRow.id)).all()
            return [Trainer.model_validate(row) for row in rows]

    def get_trainer(self, trainer_id: str) -> Trainer:
        with self.sessions() as db:
            return Trainer.model_validate(self._trainer_row(db, trainer_id))

    def create_trainer(self, payload: TrainerCreate) -> Trainer:
        with self._unique_guard():
            with self.sessions.begin() as db:
                row = TrainerRow(id=self._next_id(db, TrainerRow, "T"), status="active",
                                 **payload.model_dump())
                db.add(row)
                db.flush()
                result = Trainer.model_validate(row)
        return result

    def set_trainer_status(self, trainer_id: str, status: str) -> Trainer:
        with self.sessions.begin() as db:
            row = self._trainer_row(db, trainer_id)
            if status == "inactive" and row.status == "active":
                planned = db.scalar(
                    select(SessionRow.id)
                    .where(SessionRow.trainer_id == trainer_id, SessionRow.status == "scheduled")
                    .limit(1)
                )
                if planned is not None:
                    raise Conflict("Trainer has scheduled sessions and cannot be deactivated")
            row.status = status
            result = Trainer.model_validate(row)
        return result

    def list_availability(self, trainer_id: str) -> list[Availability]:
        with self.sessions() as db:
            self._trainer_row(db, trainer_id)
            rows = db.scalars(
                select(AvailabilityRow)
                .where(AvailabilityRow.trainer_id == trainer_id)
                .order_by(AvailabilityRow.starts_at)
            ).all()
            return [Availability.model_validate(row) for row in rows]

    def add_availability(self, trainer_id: str, payload: AvailabilityCreate) -> Availability:
        with self._unique_guard():
            with self.sessions.begin() as db:
                trainer = self._trainer_row(db, trainer_id)
                if trainer.status != "active":
                    raise Conflict("Trainer is inactive")

                existing = db.scalars(
                    select(AvailabilityRow).where(AvailabilityRow.trainer_id == trainer_id)
                ).all()
                if any(overlaps(payload.starts_at, payload.ends_at, b.starts_at, b.ends_at)
                       for b in existing):
                    raise Conflict("Availability block overlaps an existing block")

                row = AvailabilityRow(id=self._next_id(db, AvailabilityRow, "A"),
                                      trainer_id=trainer_id, **payload.model_dump())
                db.add(row)
                db.flush()
                result = Availability.model_validate(row)
        return result

    def list_sessions(self) -> list[Session]:
        with self.sessions() as db:
            rows = db.scalars(select(SessionRow).order_by(SessionRow.id)).all()
            return [Session.model_validate(row) for row in rows]

    def get_session(self, session_id: str) -> Session:
        with self.sessions() as db:
            return Session.model_validate(self._session_row(db, session_id))

    def create_session(self, payload: SessionCreate) -> Session:
        with self._unique_guard():
            with self.sessions.begin() as db:
                trainer = self._trainer_row(db, payload.trainer_id)
                if trainer.status != "active":
                    raise Conflict("Trainer is inactive")

                start, end = payload.starts_at, payload.ends_at
                inside_block = db.scalar(
                    select(AvailabilityRow.id)
                    .where(AvailabilityRow.trainer_id == trainer.id,
                           AvailabilityRow.starts_at <= start,
                           AvailabilityRow.ends_at >= end)
                    .limit(1)
                )
                if inside_block is None:
                    raise Conflict("Session is outside trainer availability")

                planned = db.scalars(
                    select(SessionRow).where(SessionRow.trainer_id == trainer.id,
                                             SessionRow.status == "scheduled")
                ).all()
                if any(overlaps(start, end, s.starts_at, s.ends_at) for s in planned):
                    raise Conflict("Trainer already has a session at this time")

                row = SessionRow(id=self._next_id(db, SessionRow, "S"), status="scheduled",
                                 **payload.model_dump())
                db.add(row)
                db.flush()
                result = Session.model_validate(row)
        return result

    def cancel_session(self, session_id: str) -> Session:
        with self.sessions.begin() as db:
            row = self._session_row(db, session_id)
            if row.status != "scheduled":
                raise Conflict(f"Cannot cancel session with status '{row.status}'")
            row.status = "cancelled"
            result = Session.model_validate(row)
        return result

    @staticmethod
    def _trainer_row(db, trainer_id: str) -> TrainerRow:
        row = db.get(TrainerRow, trainer_id)
        if row is None:
            raise NotFound("Trainer not found")
        return row

    @staticmethod
    def _session_row(db, session_id: str) -> SessionRow:
        row = db.get(SessionRow, session_id)
        if row is None:
            raise NotFound("Session not found")
        return row

    @staticmethod
    def _next_id(db, model, prefix: str) -> str:
        ids = db.scalars(select(model.id)).all()
        numbers = [int(value.split("-")[1]) for value in ids]
        return f"{prefix}-{max(numbers, default=0) + 1:03d}"

    @staticmethod
    @contextmanager
    def _unique_guard():
        try:
            yield
        except IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc.orig):
                raise Conflict("Resource with this id already exists") from exc
            raise
