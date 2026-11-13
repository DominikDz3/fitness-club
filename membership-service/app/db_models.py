from datetime import date

from sqlalchemy import CheckConstraint, Date, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MembershipRow(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint("valid_to > valid_from", name="ck_memberships_dates"),
        CheckConstraint("type IN ('open', 'morning', 'gym_only')", name="ck_memberships_type"),
        CheckConstraint("status IN ('active', 'suspended', 'expired')", name="ck_memberships_status"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    member_id: Mapped[str] = mapped_column(String(50), index=True)
    type: Mapped[str] = mapped_column(String(20))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))
    suspended_until: Mapped[date | None] = mapped_column(Date, nullable=True)
