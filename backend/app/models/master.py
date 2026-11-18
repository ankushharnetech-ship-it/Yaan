from datetime import date

from sqlalchemy import (
    JSON, Boolean, CheckConstraint, Date, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import ActiveStatus, str_enum


def _status():
    return mapped_column(str_enum(ActiveStatus), default=ActiveStatus.ACTIVE, nullable=False)


class LookupValue(Base):
    """Master-data pick lists: vehicle_type, fuel_type, license_type, induction_type, trip_type."""

    __tablename__ = "lookup_values"
    __table_args__ = (UniqueConstraint("category", "code", name="uq_lookup_category_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("vendor_id", "code", name="uq_customer_vendor_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    contact_person: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(Text)  # required by the API; nullable only for records created before it was
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ActiveStatus] = _status()


class Site(Base, TimestampMixin):
    """An office/location of a customer. A customer can have many."""

    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("customer_id", "name", name="uq_site_customer_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    city: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ActiveStatus] = _status()


class Employee(Base, TimestampMixin):
    __tablename__ = "employees"
    __table_args__ = (UniqueConstraint("customer_id", "employee_code", name="uq_employee_customer_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    site_id: Mapped[int | None] = mapped_column(ForeignKey("sites.id"), index=True)
    employee_code: Mapped[str] = mapped_column(String(50), nullable=False)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    mobile: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))
    gender: Mapped[str] = mapped_column(String(10), nullable=False)  # drives the escort-seat rule
    department: Mapped[str | None] = mapped_column(String(100))
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shift_definitions.id"))
    address: Mapped[str | None] = mapped_column(Text)  # home address: pickup point on Pickup trips, drop point on Drop trips
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    status: Mapped[ActiveStatus] = _status()


class Driver(Base, TimestampMixin):
    __tablename__ = "drivers"
    __table_args__ = (UniqueConstraint("vendor_id", "license_number", name="uq_driver_vendor_license"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)  # DRV-00001, system generated
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_number: Mapped[str] = mapped_column(String(20), nullable=False)
    email: Mapped[str | None] = mapped_column(String(254))  # optional; used for email notifications (else the linked login's email)
    gender: Mapped[str] = mapped_column(String(10), nullable=False)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    date_of_joining: Mapped[date | None] = mapped_column(Date)
    experience_months: Mapped[int | None] = mapped_column(Integer)
    license_type_id: Mapped[int] = mapped_column(ForeignKey("lookup_values.id"), nullable=False)
    license_number: Mapped[str] = mapped_column(String(50), nullable=False)
    emergency_contact: Mapped[str | None] = mapped_column(String(20))
    rest_days: Mapped[list | None] = mapped_column(JSON)
    languages: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[ActiveStatus] = _status()
    status_comment: Mapped[str | None] = mapped_column(Text)
    home_address: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    induction_date: Mapped[date | None] = mapped_column(Date)
    induction_type_id: Mapped[int | None] = mapped_column(ForeignKey("lookup_values.id"))
    default_vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_vehicle_capacity_positive"),
        UniqueConstraint("vendor_id", "vehicle_code", name="uq_vehicle_vendor_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str | None] = mapped_column(String(20), unique=True)  # VEH-00001, system generated
    vendor_id: Mapped[int] = mapped_column(ForeignKey("vendors.id"), nullable=False, index=True)
    vehicle_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # normalised, upper-case
    vehicle_code: Mapped[str] = mapped_column(String(50), nullable=False)
    vehicle_type_id: Mapped[int] = mapped_column(ForeignKey("lookup_values.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ActiveStatus] = _status()
    make: Mapped[str | None] = mapped_column(String(100))
    chassis_number: Mapped[str | None] = mapped_column(String(60))
    fuel_type_id: Mapped[int | None] = mapped_column(ForeignKey("lookup_values.id"))
    induction_type_id: Mapped[int | None] = mapped_column(ForeignKey("lookup_values.id"))
    induction_date: Mapped[date | None] = mapped_column(Date)
    gps_imei: Mapped[str | None] = mapped_column(String(30))
    billing_profile: Mapped[str | None] = mapped_column(String(100))
    date_of_joining: Mapped[date | None] = mapped_column(Date)
    shed_location: Mapped[str | None] = mapped_column(Text)
    locality: Mapped[str | None] = mapped_column(String(100))
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
