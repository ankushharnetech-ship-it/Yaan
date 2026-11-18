import re
from datetime import date

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import Body, StatusBody, check_lookup, ensure_unique, get_scoped, resolve_vendor_id
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import ActiveStatus, User, Vehicle, Vendor
from app.services import audit

router = APIRouter(prefix="/vehicles", tags=["vehicles"])


class VehicleIn(Body):
    vendor_id: int | None = None
    vehicle_number: str = Field(min_length=3, max_length=20)
    vehicle_code: str = Field(min_length=1, max_length=50)
    vehicle_type_id: int
    model: str = Field(min_length=1, max_length=100)
    capacity: int = Field(gt=0, le=100)  # seats available to passengers
    make: str | None = Field(default=None, max_length=100)
    chassis_number: str | None = Field(default=None, max_length=60)
    fuel_type_id: int | None = None
    induction_type_id: int | None = None
    induction_date: date | None = None
    gps_imei: str | None = Field(default=None, max_length=30)
    billing_profile: str | None = Field(default=None, max_length=100)
    date_of_joining: date | None = None
    shed_location: str | None = None
    locality: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str | None
    vendor_id: int
    vendor_name: str | None = None
    vehicle_number: str
    vehicle_code: str
    vehicle_type_id: int
    model: str
    capacity: int
    status: ActiveStatus
    make: str | None
    chassis_number: str | None
    fuel_type_id: int | None
    induction_type_id: int | None
    induction_date: date | None
    gps_imei: str | None
    billing_profile: str | None
    date_of_joining: date | None
    shed_location: str | None
    locality: str | None
    latitude: float | None
    longitude: float | None


def normalise_number(v: str) -> str:
    """'mh 12-ab 1234' -> 'MH12AB1234' so the same plate can't be entered twice."""
    return re.sub(r"[\s\-]", "", v).upper()


def _out(db: Session, v: Vehicle) -> VehicleOut:
    o = VehicleOut.model_validate(v)
    o.vendor_name = db.scalar(select(Vendor.name).where(Vendor.id == v.vendor_id))
    return o


def _validate(db: Session, body: VehicleIn, vendor_id: int, number: str, exclude_id: int | None = None) -> None:
    check_lookup(db, body.vehicle_type_id, "vehicle_type", "vehicle_type_id", required=True)
    check_lookup(db, body.fuel_type_id, "fuel_type", "fuel_type_id")
    check_lookup(db, body.induction_type_id, "induction_type", "induction_type_id")
    ensure_unique(db, Vehicle, "vehicle_number", number, exclude_id=exclude_id)
    ensure_unique(db, Vehicle, "vehicle_code", body.vehicle_code, exclude_id=exclude_id, vendor_id=vendor_id)


@router.get("")
def list_vehicles(
    q: str | None = None, status: ActiveStatus | None = None, vendor_id: int | None = None,
    vehicle_type_id: int | None = None, limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    _: User = Depends(require_permission("vehicle:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = []
    if not scope.is_global:
        cond.append(Vehicle.vendor_id == scope.vendor_id)
    elif vendor_id:
        cond.append(Vehicle.vendor_id == vendor_id)
    if status:
        cond.append(Vehicle.status == status)
    if vehicle_type_id:
        cond.append(Vehicle.vehicle_type_id == vehicle_type_id)
    if q:
        like = f"%{q}%"
        cond.append(or_(Vehicle.vehicle_number.ilike(like), Vehicle.vehicle_code.ilike(like),
                        Vehicle.model.ilike(like), Vehicle.code.ilike(like)))
    total = db.scalar(select(func.count()).select_from(Vehicle).where(*cond))
    rows = db.scalars(select(Vehicle).where(*cond).order_by(Vehicle.vehicle_number).limit(limit).offset(offset)).all()
    return {"total": total, "items": [_out(db, v) for v in rows]}


@router.post("", response_model=VehicleOut, status_code=201)
def create_vehicle(body: VehicleIn, actor: User = Depends(require_permission("vehicle:write")),
                   scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    vid = resolve_vendor_id(scope, body.vendor_id, db)
    number = normalise_number(body.vehicle_number)
    _validate(db, body, vid, number)
    v = Vehicle(**body.model_dump(exclude={"vendor_id", "vehicle_number"}), vehicle_number=number, vendor_id=vid)
    db.add(v)
    db.flush()
    v.code = f"VEH-{v.id:05d}"
    audit.record(db, "vehicle.created", actor, entity_type="vehicle", entity_id=v.id, vendor_id=vid)
    db.commit()
    return _out(db, v)


@router.get("/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(vehicle_id: int, _: User = Depends(require_permission("vehicle:read")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    return _out(db, get_scoped(db, scope, Vehicle, vehicle_id))


@router.put("/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(vehicle_id: int, body: VehicleIn, actor: User = Depends(require_permission("vehicle:write")),
                   scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    v = get_scoped(db, scope, Vehicle, vehicle_id)
    number = normalise_number(body.vehicle_number)
    _validate(db, body, v.vendor_id, number, exclude_id=v.id)
    for k, val in body.model_dump(exclude={"vendor_id", "vehicle_number"}).items():
        setattr(v, k, val)
    v.vehicle_number = number
    audit.record(db, "vehicle.updated", actor, entity_type="vehicle", entity_id=v.id, vendor_id=v.vendor_id)
    db.commit()
    return _out(db, v)


@router.patch("/{vehicle_id}/status", response_model=VehicleOut)
def set_vehicle_status(vehicle_id: int, body: StatusBody, actor: User = Depends(require_permission("vehicle:write")),
                       scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    v = get_scoped(db, scope, Vehicle, vehicle_id)
    v.status = body.status
    audit.record(db, f"vehicle.{'activated' if body.status == ActiveStatus.ACTIVE else 'deactivated'}", actor,
                 entity_type="vehicle", entity_id=v.id, vendor_id=v.vendor_id)
    db.commit()
    return _out(db, v)
