from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db_models import MembershipRow
from app.models import Membership, MembershipCreate

CURRENT_STATUSES = ("active", "suspended")

SEED_DATA = [
    dict(id="M-001", member_id="U-100", type="open",
         valid_from=date(2026, 10, 1), valid_to=date(2026, 12, 31),
         status="active", suspended_until=None),
    dict(id="M-002", member_id="U-200", type="morning",
         valid_from=date(2026, 9, 1), valid_to=date(2026, 11, 30),
         status="suspended", suspended_until=date(2026, 10, 25)),
]


class MembershipNotFound(LookupError):
    pass


class MembershipConflict(ValueError):
    pass


class MembershipRepository:
    """Every operation opens its own session; sessions.begin() commits on success, rolls back on exception."""

    def __init__(self, sessions, today=date.today):
        self.sessions = sessions
        self.today = today

    def _refresh_status(self, row: MembershipRow) -> None:
        today = self.today()
        if row.status == "suspended" and row.suspended_until is not None and row.suspended_until <= today:
            row.status = "active"
            row.suspended_until = None
        if row.status == "active" and row.valid_to < today:
            row.status = "expired"

    def seed(self):
        with self.sessions.begin() as db:
            if db.scalar(select(func.count()).select_from(MembershipRow)) == 0:
                db.add_all([MembershipRow(**data) for data in SEED_DATA])

    # Odczyty też otwierają transakcję (begin), bo odświeżony status zapisuje się w bazie.
    def list(self) -> list[Membership]:
        with self.sessions.begin() as db:
            rows = db.scalars(select(MembershipRow).order_by(MembershipRow.id)).all()
            for row in rows:
                self._refresh_status(row)
            result = [Membership.model_validate(row) for row in rows]
        return result

    def get(self, membership_id: str) -> Membership:
        with self.sessions.begin() as db:
            row = self._get_row(db, membership_id)
            self._refresh_status(row)
            result = Membership.model_validate(row)
        return result

    def create(self, payload: MembershipCreate) -> Membership:
        try:
            with self.sessions.begin() as db:
                current = db.scalars(
                    select(MembershipRow)
                    .where(MembershipRow.member_id == payload.member_id,
                           MembershipRow.status.in_(CURRENT_STATUSES))
                ).all()
                for row in current:
                    self._refresh_status(row)
                if any(row.status in CURRENT_STATUSES for row in current):
                    raise MembershipConflict("Member already has a current membership")

                row = MembershipRow(id=self._next_id(db), status="active", **payload.model_dump())
                db.add(row)
                db.flush()
                result = Membership.model_validate(row)
            return result
        except IntegrityError as exc:
            if "UNIQUE constraint failed" in str(exc.orig):
                raise MembershipConflict("Membership with this id already exists") from exc
            raise

    def suspend(self, membership_id: str, days: int) -> Membership:
        with self.sessions.begin() as db:
            row = self._get_row(db, membership_id)
            self._refresh_status(row)
            if row.status != "active":
                raise MembershipConflict(f"Cannot suspend membership with status '{row.status}'")

            row.status = "suspended"
            row.suspended_until = self.today() + timedelta(days=days)
            row.valid_to = row.valid_to + timedelta(days=days)
            result = Membership.model_validate(row)
        return result

    def resume(self, membership_id: str) -> Membership:
        with self.sessions.begin() as db:
            row = self._get_row(db, membership_id)
            self._refresh_status(row)
            if row.status != "suspended":
                raise MembershipConflict(f"Cannot resume membership with status '{row.status}'")

            row.status = "active"
            row.suspended_until = None
            result = Membership.model_validate(row)
        return result

    @staticmethod
    def _get_row(db, membership_id: str) -> MembershipRow:
        row = db.get(MembershipRow, membership_id)
        if row is None:
            raise MembershipNotFound(membership_id)
        return row

    @staticmethod
    def _next_id(db) -> str:
        ids = db.scalars(select(MembershipRow.id)).all()
        numbers = [int(membership_id.split("-")[1]) for membership_id in ids]
        return f"M-{max(numbers, default=0) + 1:03d}"