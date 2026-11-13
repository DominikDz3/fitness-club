from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TrainerRow(Base):
    __tablename__ = "trainers"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'inactive')", name="ck_trainers_status"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    specialization: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))


class AvailabilityRow(Base):
    __tablename__ = "availability_blocks"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_availability_times"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    trainer_id: Mapped[str] = mapped_column(ForeignKey("trainers.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)


class SessionRow(Base):
    __tablename__ = "training_sessions"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_sessions_times"),
        CheckConstraint("status IN ('scheduled', 'cancelled')", name="ck_sessions_status"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    trainer_id: Mapped[str] = mapped_column(ForeignKey("trainers.id"), index=True)
    membership_id: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))
