from datetime import datetime, time

from sqlalchemy import (
    CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint, text, func, Boolean,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import ActiveStatus, TripStatus, str_enum


class ShiftDefinition(Base, TimestampMixin):
    """Shift timings are defined per customer by the vendor."""

    __tablename__ = "shift_definitions"
    __table_args__ = (UniqueConstraint("customer_id", "name", name="uq_shift_customer_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)  # may be earlier than start (overnight shift)
    status: Mapped[ActiveStatus] = mapped_column(str_enum(ActiveStatus), default=ActiveStatus.ACTIVE, nullable=False)


class Trip(Base, TimestampMixin):
    __tablename__ = "trips"
    __table_args__ = (
        CheckConstraint("scheduled_end > scheduled_start", name="ck_trip_end_after_start"),
        CheckConstraint("block_end >= scheduled_end", name="ck_trip_block_end"),
        # Hard guarantee against double-booking even under concurrent requests. A trip occupies
        # [scheduled_start, scheduled_end + buffer); two trips of one resource may not overlap, which
        # is exactly the "30 minutes between trips" rule. Cancelled trips don't count.
        ExcludeConstraint(
            ("driver_id", "="), (text("tstzrange(scheduled_start, block_end)"), "&&"),
            where=text("status <> 'cancelled'"), using="gist", name="ex_trip_driver_overlap",
        ),
        ExcludeConstraint(
            ("vehicle_id", "="), (text("tstzrange(scheduled_start, block_end)"), "&&"),
            where=text("status <> 'cancelled'"), using="gist", name="ex_trip_vehicle_overlap",
        ),
        Index("ix_trips_vendor_start", "vendor_id", "scheduled_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)  # TRP-000001
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    site_id: Mapped[int] = mapped_column(ForeignKey("sites.id"), nullable=False)
    trip_type_id: Mapped[int] = mapped_column(ForeignKey("lookup_values.id"), nullable=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shift_definitions.id"))

    scheduled_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scheduled_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    block_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)  # end + buffer

    route_name: Mapped[str | None] = mapped_column(String(200))
    special_instructions: Mapped[str | None] = mapped_column(Text)
    pickup_address: Mapped[str] = mapped_column(Text, nullable=False)
    pickup_latitude: Mapped[float | None] = mapped_column(Float)
    pickup_longitude: Mapped[float | None] = mapped_column(Float)
    drop_address: Mapped[str] = mapped_column(Text, nullable=False)
    drop_latitude: Mapped[float | None] = mapped_column(Float)
    drop_longitude: Mapped[float | None] = mapped_column(Float)

    passenger_count: Mapped[int] = mapped_column(Integer, nullable=False)
    escort_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    required_capacity: Mapped[int] = mapped_column(Integer, nullable=False)  # passengers + escort seat

    # NULL while the trip is a request awaiting assignment (status "scheduled"); set when a Vendor Admin assigns.
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), index=True)

    status: Mapped[TripStatus] = mapped_column(str_enum(TripStatus), default=TripStatus.ASSIGNED, nullable=False, index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    # Last position reported by the driver's device while the trip is started (live map). Not a history.
    last_latitude: Mapped[float | None] = mapped_column(Float)
    last_longitude: Mapped[float | None] = mapped_column(Float)
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripPassenger(Base):
    __tablename__ = "trip_passengers"
    __table_args__ = (UniqueConstraint("trip_id", "employee_id", name="uq_trip_passenger"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)  # stop order along the shared route
    address: Mapped[str | None] = mapped_column(Text)  # employee's address at booking time (snapshot)
    # snapshots so history survives later employee edits
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)

    # Drop-off confirmation. The OTP itself is never stored: it is derived from this random seed + a server secret
    # (see services/otp.py), so reading the database alone does not reveal it. NULL until the trip is assigned.
    otp_seed: Mapped[str | None] = mapped_column(String(32))
    otp_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    otp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    otp_verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # The driver's way out when an employee doesn't show up or can't share the OTP (reason required, flagged to admins).
    not_dropped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    not_dropped_reason: Mapped[str | None] = mapped_column(Text)
    not_dropped_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class TripAssignment(Base):
    """History of which driver+vehicle served a trip."""

    __tablename__ = "trip_assignments"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), nullable=False)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False)
    assigned_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TripStatusHistory(Base):
    __tablename__ = "trip_status_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
