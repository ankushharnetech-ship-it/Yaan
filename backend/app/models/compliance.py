from datetime import date

from sqlalchemy import CheckConstraint, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import ActiveStatus, str_enum


class ComplianceItem(Base, TimestampMixin):
    """A dated compliance record (licence, insurance, permit…) for one driver or one vehicle.
    No files are stored – only the type, reference and dates. Items are retired (inactive), never deleted."""

    __tablename__ = "compliance_items"
    __table_args__ = (
        CheckConstraint(
            "(subject_type = 'driver' AND driver_id IS NOT NULL AND vehicle_id IS NULL) OR "
            "(subject_type = 'vehicle' AND vehicle_id IS NOT NULL AND driver_id IS NULL)",
            name="ck_compliance_one_subject",
        ),
        CheckConstraint("issue_date IS NULL OR expiry_date >= issue_date", name="ck_compliance_dates"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(10), nullable=False)  # driver | vehicle
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    doc_type_id: Mapped[int] = mapped_column(ForeignKey("lookup_values.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(120))  # for custom ("Other") documents
    reference_number: Mapped[str | None] = mapped_column(String(100))
    issue_date: Mapped[date | None] = mapped_column(Date)
    expiry_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[ActiveStatus] = mapped_column(str_enum(ActiveStatus), default=ActiveStatus.ACTIVE, nullable=False)
