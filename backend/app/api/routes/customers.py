from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import (Body, StatusBody, ensure_unique, field_error, get_scoped, operator_customer, resolve_vendor_id,
                            validate_mobile)
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import ActiveStatus, Customer, Site, User, Vendor
from app.services import audit

router = APIRouter(tags=["customers"])


# ---------------- Customers ----------------
class CustomerIn(Body):
    vendor_id: int | None = None  # Super Admin only; others are pinned to their own vendor
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    contact_person: str = Field(min_length=1, max_length=200)  # required
    email: EmailStr  # required
    phone: str | None = None
    address: str = Field(min_length=1)  # required
    latitude: float = Field(ge=-90, le=90)  # required
    longitude: float = Field(ge=-180, le=180)  # required

    _phone = field_validator("phone")(validate_mobile)


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vendor_id: int
    vendor_name: str | None = None
    code: str
    name: str
    contact_person: str | None
    email: str | None
    phone: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    status: ActiveStatus
    site_count: int = 0


def _out(db: Session, c: Customer) -> CustomerOut:
    o = CustomerOut.model_validate(c)
    o.vendor_name = db.scalar(select(Vendor.name).where(Vendor.id == c.vendor_id))
    o.site_count = db.scalar(select(func.count()).select_from(Site).where(Site.customer_id == c.id)) or 0
    return o


@router.get("/customers")
def list_customers(
    q: str | None = None, status: ActiveStatus | None = None, vendor_id: int | None = None,
    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("customer:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = []
    if (mine := operator_customer(user)) is not None:
        cond.append(Customer.id == mine)
    if not scope.is_global:
        cond.append(Customer.vendor_id == scope.vendor_id)
    elif vendor_id:
        cond.append(Customer.vendor_id == vendor_id)
    if status:
        cond.append(Customer.status == status)
    if q:
        cond.append(or_(Customer.name.ilike(f"%{q}%"), Customer.code.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(Customer).where(*cond))
    rows = db.scalars(select(Customer).where(*cond).order_by(Customer.name).limit(limit).offset(offset)).all()
    return {"total": total, "items": [_out(db, c) for c in rows]}


@router.post("/customers", response_model=CustomerOut, status_code=201)
def create_customer(body: CustomerIn, actor: User = Depends(require_permission("customer:write")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    vid = resolve_vendor_id(scope, body.vendor_id, db)
    ensure_unique(db, Customer, "code", body.code, vendor_id=vid)
    c = Customer(**body.model_dump(exclude={"vendor_id", "email"}), vendor_id=vid,
                 email=str(body.email) if body.email else None)
    db.add(c)
    db.flush()
    audit.record(db, "customer.created", actor, entity_type="customer", entity_id=c.id, vendor_id=vid)
    db.commit()
    return _out(db, c)


@router.get("/customers/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, _: User = Depends(require_permission("customer:read")),
                 scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    return _out(db, get_scoped(db, scope, Customer, customer_id))


@router.put("/customers/{customer_id}", response_model=CustomerOut)
def update_customer(customer_id: int, body: CustomerIn, actor: User = Depends(require_permission("customer:write")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    c = get_scoped(db, scope, Customer, customer_id)
    ensure_unique(db, Customer, "code", body.code, exclude_id=c.id, vendor_id=c.vendor_id)
    for k, v in body.model_dump(exclude={"vendor_id", "email"}).items():
        setattr(c, k, v)
    c.email = str(body.email) if body.email else None
    audit.record(db, "customer.updated", actor, entity_type="customer", entity_id=c.id, vendor_id=c.vendor_id)
    db.commit()
    return _out(db, c)


@router.patch("/customers/{customer_id}/status", response_model=CustomerOut)
def set_customer_status(customer_id: int, body: StatusBody, actor: User = Depends(require_permission("customer:write")),
                        scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    c = get_scoped(db, scope, Customer, customer_id)
    c.status = body.status
    audit.record(db, f"customer.{'activated' if body.status == ActiveStatus.ACTIVE else 'deactivated'}", actor,
                 entity_type="customer", entity_id=c.id, vendor_id=c.vendor_id)
    db.commit()
    return _out(db, c)


# ---------------- Sites (a customer can have many offices in different locations) ----------------
class SiteIn(Body):
    customer_id: int | None = None  # required on create; immutable afterwards
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1)
    city: str | None = Field(default=None, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class SiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    vendor_id: int
    name: str
    address: str
    city: str | None
    latitude: float | None
    longitude: float | None
    status: ActiveStatus


@router.get("/sites")
def list_sites(
    customer_id: int | None = None, status: ActiveStatus | None = None,
    limit: int = Query(200, ge=1, le=500), offset: int = Query(0, ge=0),
    _: User = Depends(require_permission("customer:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = []
    if not scope.is_global:
        cond.append(Site.vendor_id == scope.vendor_id)
    if customer_id:
        cond.append(Site.customer_id == customer_id)
    if status:
        cond.append(Site.status == status)
    total = db.scalar(select(func.count()).select_from(Site).where(*cond))
    rows = db.scalars(select(Site).where(*cond).order_by(Site.name).limit(limit).offset(offset)).all()
    return {"total": total, "items": [SiteOut.model_validate(s) for s in rows]}


@router.post("/sites", response_model=SiteOut, status_code=201)
def create_site(body: SiteIn, actor: User = Depends(require_permission("customer:write")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    if body.customer_id is None:
        raise field_error("customer_id", "Customer is required")
    cust = get_scoped(db, scope, Customer, body.customer_id)
    ensure_unique(db, Site, "name", body.name, customer_id=cust.id)
    s = Site(**body.model_dump(exclude={"customer_id"}), customer_id=cust.id, vendor_id=cust.vendor_id)
    db.add(s)
    db.flush()
    audit.record(db, "site.created", actor, entity_type="site", entity_id=s.id, vendor_id=s.vendor_id)
    db.commit()
    return s


@router.put("/sites/{site_id}", response_model=SiteOut)
def update_site(site_id: int, body: SiteIn, actor: User = Depends(require_permission("customer:write")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    s = get_scoped(db, scope, Site, site_id)
    ensure_unique(db, Site, "name", body.name, exclude_id=s.id, customer_id=s.customer_id)
    for k, v in body.model_dump(exclude={"customer_id"}).items():
        setattr(s, k, v)
    audit.record(db, "site.updated", actor, entity_type="site", entity_id=s.id, vendor_id=s.vendor_id)
    db.commit()
    return s


@router.patch("/sites/{site_id}/status", response_model=SiteOut)
def set_site_status(site_id: int, body: StatusBody, actor: User = Depends(require_permission("customer:write")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    s = get_scoped(db, scope, Site, site_id)
    s.status = body.status
    audit.record(db, f"site.{'activated' if body.status == ActiveStatus.ACTIVE else 'deactivated'}", actor,
                 entity_type="site", entity_id=s.id, vendor_id=s.vendor_id)
    db.commit()
    return s
