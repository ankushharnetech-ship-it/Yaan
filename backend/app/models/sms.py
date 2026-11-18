from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SmsLog(Base):
    """One row per SMS. Written in the same transaction as the trip change that causes it, so there is
    always a record (status 'pending') even if the provider is down; delivery happens afterwards."""

    __tablename__ = "sms_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"), index=True)
    recipient_type: Mapped[str] = mapped_column(String(20), nullable=False)  # driver | employee
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), index=True)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    recipient_name: Mapped[str | None] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    template: Mapped[str] = mapped_column(String(60), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)  # pending|sent|delivered|failed
    provider_message_id: Mapped[str | None] = mapped_column(String(64), index=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
