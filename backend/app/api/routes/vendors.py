from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import Body, StatusBody, ensure_unique, get_scoped, validate_mobile
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import ActiveStatus, User, Vendor
from app.services import audit

router = APIRouter(prefix="/vendors", tags=["vendors"])


class VendorIn(Body):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_-]+$")
    contact_name: str = Field(min_length=1, max_length=200)  # primary contact - required
    email: EmailStr  # required
    mobile: str | None = None
    address: str = Field(min_length=1)  # required

    _mobile = field_validator("mobile")(validate_mobile)


class VendorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    code: str
    contact_name: str | None
    email: str | None
    mobile: str | None
    address: str | None
    status: ActiveStatus


@router.get("")
def list_vendors(
    q: str | None = None,
    status: ActiveStatus | None = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_permission("vendor:read")),
    scope: VendorScope = Depends(get_vendor_scope),
    db: Session = Depends(get_db),
):
    cond = []
    if not scope.is_global:
        cond.append(Vendor.id == scope.vendor_id)
    if status:
        cond.append(Vendor.status == status)
    if q:
        cond.append(or_(Vendor.name.ilike(f"%{q}%"), Vendor.code.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(Vendor).where(*cond))
    rows = db.scalars(select(Vendor).where(*cond).order_by(Vendor.name).limit(limit).offset(offset)).all()
    return {"total": total, "items": [VendorOut.model_validate(v) for v in rows]}


@router.post("", response_model=VendorOut, status_code=201)
def create_vendor(body: VendorIn, actor: User = Depends(require_permission("vendor:write")), db: Session = Depends(get_db)):
    ensure_unique(db, Vendor, "code", body.code)
    v = Vendor(**body.model_dump(exclude={"email"}), email=str(body.email) if body.email else None)
    db.add(v)
    db.flush()
    audit.record(db, "vendor.created", actor, entity_type="vendor", entity_id=v.id, vendor_id=v.id)
    db.commit()
    return v


@router.get("/{vendor_id}", response_model=VendorOut)
def get_vendor(vendor_id: int, _: User = Depends(require_permission("vendor:read")),
               scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    return get_scoped(db, scope, Vendor, vendor_id, vendor_field="id")


@router.put("/{vendor_id}", response_model=VendorOut)
def update_vendor(vendor_id: int, body: VendorIn, actor: User = Depends(require_permission("vendor:write")),
                  db: Session = Depends(get_db)):
    v = get_scoped(db, VendorScope(None), Vendor, vendor_id, vendor_field="id")
    ensure_unique(db, Vendor, "code", body.code, exclude_id=v.id)
    for k, val in body.model_dump(exclude={"email"}).items():
        setattr(v, k, val)
    v.email = str(body.email) if body.email else None
    audit.record(db, "vendor.updated", actor, entity_type="vendor", entity_id=v.id, vendor_id=v.id)
    db.commit()
    return v


@router.patch("/{vendor_id}/status", response_model=VendorOut)
def set_vendor_status(vendor_id: int, body: StatusBody, actor: User = Depends(require_permission("vendor:write")),
                      db: Session = Depends(get_db)):
    v = get_scoped(db, VendorScope(None), Vendor, vendor_id, vendor_field="id")
    v.status = body.status
    audit.record(db, f"vendor.{'activated' if body.status == ActiveStatus.ACTIVE else 'deactivated'}", actor,
                 entity_type="vendor", entity_id=v.id, vendor_id=v.id)
    db.commit()
    return v
