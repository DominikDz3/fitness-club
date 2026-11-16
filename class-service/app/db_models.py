from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GroupClassRow(Base):
    __tablename__ = "group_classes"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_classes_times"),
        CheckConstraint("capacity BETWEEN 1 AND 50", name="ck_classes_capacity"),
        CheckConstraint("status IN ('scheduled', 'finished', 'cancelled')", name="ck_classes_status"),
    )

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    trainer_id: Mapped[str] = mapped_column(String(16), index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    capacity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))