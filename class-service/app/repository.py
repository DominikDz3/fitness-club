from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db_models import GroupClassRow
from app.models import GroupClass, GroupClassCreate

SEED_CLASSES = [
    dict(id="C-001", name="Trening obwodowy", trainer_id="T-001",
         starts_at=datetime(2026, 11, 20, 18, 0), ends_at=datetime(2026, 11, 20, 19, 0),
         capacity=12, status="scheduled"),
    dict(id="C-002", name="Pilates", trainer_id="T-001",
         starts_at=datetime(2026, 11, 18, 17, 0), ends_at=datetime(2026, 11, 18, 18, 0),
         capacity=10, status="cancelled"),
]

ALLOWED_TRANSITIONS = {
    "scheduled": {"finished", "cancelled"},
    "finished": set(),
    "cancelled": set(),
}


class NotFound(LookupError):
    """Brak zasobu -> 404."""


class Conflict(ValueError):
    """Poprawne dane sprzeczne z aktualnym stanem -> 409."""


def overlaps(start_a, end_a, start_b, end_b) -> bool:
    return start_a < end_b and start_b < end_a


class ClassRepository:

    def __init__(self, sessions):
        self.sessions = sessions

    def seed(self):
        with self.sessions.begin() as db:
            if db.scalar(select(func.count()).select_from(GroupClassRow)) == 0:
                db.add_all([GroupClassRow(**data) for data in SEED_CLASSES])

    def list_classes(self) -> list[GroupClass]:
        with self.sessions() as db:
            rows = db.scalars(select(GroupClassRow).order_by(GroupClassRow.id)).all()
            return [GroupClass.model_validate(row) for row in rows]

    def get_class(self, class_id: str) -> GroupClass:
        with self.sessions() as db:
            return GroupClass.model_validate(self._class_row(db, class_id))

    def create_class(self, payload: GroupClassCreate) -> GroupClass:
        with self._unique_guard():
            with self.sessions.begin() as db:
                planned = db.scalars(
                    select(GroupClassRow).where(GroupClassRow.trainer_id == payload.trainer_id,
                                                GroupClassRow.status == "scheduled")
                ).all()
                if any(overlaps(payload.starts_at, payload.ends_at, c.starts_at, c.ends_at)
                       for c in planned):
                    raise Conflict("Trainer already has a class at this time")

                row = GroupClassRow(id=self._next_id(db), status="scheduled",
                                    **payload.model_dump())
                db.add(row)
                db.flush()
                result = GroupClass.model_validate(row)
        return result

    def change_status(self, class_id: str, new_status: str) -> GroupClass:
        with self.sessions.begin() as db:
            row = self._class_row(db, class_id)
            if new_status not in ALLOWED_TRANSITIONS[row.status]:
                raise Conflict(f"Cannot change class status from '{row.status}' to '{new_status}'")
            row.status = new_status
            result = GroupClass.model_validate(row)
        return result

    @staticmethod
    def _class_row(db, class_id: str) -> GroupClassRow:
        row = db.get(GroupClassRow, class_id)
        if row is None:
            raise NotFound("Class not found")
        return row

    @staticmethod
    def _next_id(db) -> str:
        ids = db.scalars(select(GroupClassRow.id)).all()
        numbers = [int(value.split("-")[1]) for value in ids]
        return f"C-{max(numbers, default=0) + 1:03d}"

    @staticmethod
    @contextmanager
    def _unique_guard():
        try:
            yield
        except IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc.orig):
                raise Conflict("Resource with this id already exists") from exc
            raise