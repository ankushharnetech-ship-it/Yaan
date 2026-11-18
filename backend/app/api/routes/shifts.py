"""Shift timings are defined per customer; the vendor (admin) maintains them."""
from datetime import time

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.common import Body, StatusBody, ensure_unique, field_error, get_scoped
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import ActiveStatus, Customer, ShiftDefinition, User
from app.services import audit

router = APIRouter(prefix="/shifts", tags=["shifts"])


class ShiftIn(Body):
    customer_id: int | None = None  # required on create
    name: str = Field(min_length=1, max_length=100)
    start_time: time
    end_time: time  # an earlier end than start means an overnight shift

    @field_validator("start_time", "end_time")
    @classmethod
    def _naive(cls, v: time):
        return v.replace(tzinfo=None, second=0, microsecond=0)


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    vendor_id: int
    name: str
    start_time: time
    end_time: time
    status: ActiveStatus


@router.get("")
def list_shifts(
    customer_id: int | None = None, status: ActiveStatus | None = None, q: str | None = None,
    limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
    _: User = Depends(require_permission("customer:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = [] if scope.is_global else [ShiftDefinition.vendor_id == scope.vendor_id]
    if customer_id:
        cond.append(ShiftDefinition.customer_id == customer_id)
    if status:
        cond.append(ShiftDefinition.status == status)
    if q:
        cond.append(ShiftDefinition.name.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(ShiftDefinition).where(*cond))
    rows = db.scalars(select(ShiftDefinition).where(*cond).order_by(ShiftDefinition.start_time, ShiftDefinition.name)
                      .limit(limit).offset(offset)).all()
    return {"total": total, "items": [ShiftOut.model_validate(r) for r in rows]}


@router.post("", response_model=ShiftOut, status_code=201)
def create_shift(body: ShiftIn, actor: User = Depends(require_permission("customer:write")),
                 scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    if body.customer_id is None:
        raise field_error("customer_id", "Customer is required")
    cust = get_scoped(db, scope, Customer, body.customer_id)
    ensure_unique(db, ShiftDefinition, "name", body.name, customer_id=cust.id)
    s = ShiftDefinition(**body.model_dump(exclude={"customer_id"}), customer_id=cust.id, vendor_id=cust.vendor_id)
    db.add(s)
    db.flush()
    audit.record(db, "shift.created", actor, entity_type="shift", entity_id=s.id, vendor_id=s.vendor_id)
    db.commit()
    return s


@router.put("/{shift_id}", response_model=ShiftOut)
def update_shift(shift_id: int, body: ShiftIn, actor: User = Depends(require_permission("customer:write")),
                 scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    s = get_scoped(db, scope, ShiftDefinition, shift_id)
    ensure_unique(db, ShiftDefinition, "name", body.name, exclude_id=s.id, customer_id=s.customer_id)
    s.name, s.start_time, s.end_time = body.name, body.start_time, body.end_time
    audit.record(db, "shift.updated", actor, entity_type="shift", entity_id=s.id, vendor_id=s.vendor_id)
    db.commit()
    return s


@router.patch("/{shift_id}/status", response_model=ShiftOut)
def set_shift_status(shift_id: int, body: StatusBody, actor: User = Depends(require_permission("customer:write")),
                     scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    s = get_scoped(db, scope, ShiftDefinition, shift_id)
    s.status = body.status
    audit.record(db, f"shift.{'activated' if body.status == ActiveStatus.ACTIVE else 'deactivated'}", actor,
                 entity_type="shift", entity_id=s.id, vendor_id=s.vendor_id)
    db.commit()
    return s
