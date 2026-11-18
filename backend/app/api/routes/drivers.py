from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import (
    Body, Gender, StatusBody, check_lookup, ensure_unique, field_error, get_scoped, resolve_vendor_id, validate_mobile,
)
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import ActiveStatus, Driver, Role, User, Vehicle, Vendor
from app.services import audit

router = APIRouter(prefix="/drivers", tags=["drivers"])

Day = Literal["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class DriverIn(Body):
    vendor_id: int | None = None
    first_name: str = Field(min_length=1, max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    contact_number: str
    email: EmailStr  # used for email notifications
    gender: Gender
    date_of_birth: date | None = None
    date_of_joining: date
    experience_months: int = Field(ge=0, le=1200)
    license_type_id: int
    license_number: str = Field(min_length=1, max_length=50)
    emergency_contact: str
    rest_days: list[Day] | None = None
    languages: list[str] | None = None
    status_comment: str | None = None
    home_address: str = Field(min_length=1)
    locality: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    induction_date: date | None = None
    induction_type_id: int | None = None
    default_vehicle_id: int | None = None

    @field_validator("contact_number")
    @classmethod
    def _contact(cls, v):
        out = validate_mobile(v)
        if not out:
            raise ValueError("Contact number is required")
        return out

    @field_validator("emergency_contact")
    @classmethod
    def _emergency(cls, v):
        out = validate_mobile(v)
        if not out:
            raise ValueError("Emergency contact is required")
        return out


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str | None
    vendor_id: int
    vendor_name: str | None = None
    first_name: str
    middle_name: str | None
    last_name: str
    contact_number: str
    email: str | None = None
    gender: str
    date_of_birth: date | None
    date_of_joining: date | None
    experience_months: int | None
    license_type_id: int
    license_number: str
    emergency_contact: str | None
    rest_days: list[str] | None
    languages: list[str] | None
    status: ActiveStatus
    status_comment: str | None
    home_address: str | None
    locality: str | None
    latitude: float | None
    longitude: float | None
    induction_date: date | None
    induction_type_id: int | None
    default_vehicle_id: int | None
    has_login: bool = False


class DriverBrief(BaseModel):
    """What Operators see: enough to pick a driver, no personal/sensitive details."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str | None
    first_name: str
    last_name: str
    contact_number: str
    gender: str
    status: ActiveStatus
    default_vehicle_id: int | None


def _validate(db: Session, body: DriverIn, vendor_id: int, exclude_id: int | None = None) -> None:
    check_lookup(db, body.license_type_id, "license_type", "license_type_id", required=True)
    check_lookup(db, body.induction_type_id, "induction_type", "induction_type_id")
    ensure_unique(db, Driver, "license_number", body.license_number, exclude_id=exclude_id, vendor_id=vendor_id)
    if body.default_vehicle_id is not None:
        v = db.get(Vehicle, body.default_vehicle_id)
        if v is None or v.vendor_id != vendor_id:
            raise field_error("default_vehicle_id", "Select a vehicle of the same vendor")


def _out(db: Session, d: Driver) -> DriverOut:
    o = DriverOut.model_validate(d)
    o.vendor_name = db.scalar(select(Vendor.name).where(Vendor.id == d.vendor_id))
    o.has_login = db.scalar(select(User.id).where(User.driver_id == d.id)) is not None
    return o


@router.get("")
def list_drivers(
    q: str | None = None, status: ActiveStatus | None = None, vendor_id: int | None = None,
    unlinked: bool = False, limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("driver:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = []
    if not scope.is_global:
        cond.append(Driver.vendor_id == scope.vendor_id)
    elif vendor_id:
        cond.append(Driver.vendor_id == vendor_id)
    if status:
        cond.append(Driver.status == status)
    if unlinked:  # drivers that do not yet have a login (used by user onboarding)
        cond.append(~select(User.id).where(User.driver_id == Driver.id).exists())
    if q:
        like = f"%{q}%"
        cond.append(or_(Driver.first_name.ilike(like), Driver.last_name.ilike(like), Driver.code.ilike(like),
                        Driver.contact_number.ilike(like), Driver.license_number.ilike(like)))
    total = db.scalar(select(func.count()).select_from(Driver).where(*cond))
    rows = db.scalars(select(Driver).where(*cond).order_by(Driver.first_name, Driver.id).limit(limit).offset(offset)).all()
    items = [DriverBrief.model_validate(d) for d in rows] if user.role == Role.OPERATOR else [_out(db, d) for d in rows]
    return {"total": total, "items": items}


@router.post("", response_model=DriverOut, status_code=201)
def create_driver(body: DriverIn, actor: User = Depends(require_permission("driver:write")),
                  scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    vid = resolve_vendor_id(scope, body.vendor_id, db)
    _validate(db, body, vid)
    d = Driver(**body.model_dump(exclude={"vendor_id"}), vendor_id=vid)
    db.add(d)
    db.flush()
    d.code = f"DRV-{d.id:05d}"
    audit.record(db, "driver.created", actor, entity_type="driver", entity_id=d.id, vendor_id=vid)
    db.commit()
    return _out(db, d)


@router.get("/{driver_id}", response_model=DriverOut)
def get_driver(driver_id: int, _: User = Depends(require_permission("driver:write")),
               scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    return _out(db, get_scoped(db, scope, Driver, driver_id))


@router.put("/{driver_id}", response_model=DriverOut)
def update_driver(driver_id: int, body: DriverIn, actor: User = Depends(require_permission("driver:write")),
                  scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    d = get_scoped(db, scope, Driver, driver_id)
    _validate(db, body, d.vendor_id, exclude_id=d.id)
    for k, v in body.model_dump(exclude={"vendor_id"}).items():
        setattr(d, k, v)
    audit.record(db, "driver.updated", actor, entity_type="driver", entity_id=d.id, vendor_id=d.vendor_id)
    db.commit()
    return _out(db, d)


@router.patch("/{driver_id}/status", response_model=DriverOut)
def set_driver_status(driver_id: int, body: StatusBody, actor: User = Depends(require_permission("driver:write")),
                      scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    d = get_scoped(db, scope, Driver, driver_id)
    d.status = body.status
    audit.record(db, f"driver.{'activated' if body.status == ActiveStatus.ACTIVE else 'deactivated'}", actor,
                 entity_type="driver", entity_id=d.id, vendor_id=d.vendor_id)
    db.commit()
    return _out(db, d)
