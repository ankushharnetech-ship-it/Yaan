from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import (Body, Gender, StatusBody, ensure_operator_customer, ensure_unique, field_error, get_scoped,
                            operator_customer, require_operator_customer, validate_mobile)
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import ActiveStatus, Customer, Employee, ShiftDefinition, Site, User
from app.services import audit

router = APIRouter(prefix="/employees", tags=["employees"])


class EmployeeIn(Body):
    customer_id: int | None = None  # required on create; cannot be changed later (trip history)
    site_id: int  # required
    shift_id: int  # required (shifts are defined per customer)
    employee_code: str = Field(min_length=1, max_length=50)
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    mobile: str  # required: used for trip SMS
    email: EmailStr  # required: used for email notifications
    gender: Gender  # required: drives the escort-seat rule
    department: str | None = Field(default=None, max_length=100)
    address: str = Field(min_length=1)  # required: the home address used as pickup/drop
    latitude: float = Field(ge=-90, le=90)  # required
    longitude: float = Field(ge=-180, le=180)  # required

    @field_validator("mobile")
    @classmethod
    def _mobile(cls, v):
        out = validate_mobile(v)
        if not out:
            raise ValueError("Mobile number is required")
        return out


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    vendor_id: int
    customer_id: int
    customer_name: str | None = None
    site_id: int | None
    site_name: str | None = None
    shift_id: int | None = None
    employee_code: str
    first_name: str
    last_name: str
    mobile: str
    email: str | None
    gender: str
    department: str | None
    address: str | None
    latitude: float | None
    longitude: float | None
    status: ActiveStatus


def _out(e: Employee, cust: dict[int, str], sites: dict[int, str]) -> EmployeeOut:
    o = EmployeeOut.model_validate(e)
    o.customer_name = cust.get(e.customer_id)
    o.site_name = sites.get(e.site_id) if e.site_id else None
    return o


def _names(db: Session, rows: list[Employee]):
    cust = dict(db.execute(select(Customer.id, Customer.name).where(Customer.id.in_({r.customer_id for r in rows}))).all())
    site_ids = {r.site_id for r in rows if r.site_id}
    sites = dict(db.execute(select(Site.id, Site.name).where(Site.id.in_(site_ids))).all()) if site_ids else {}
    return cust, sites


def _check_site(db: Session, site_id: int | None, customer: Customer) -> None:
    if site_id is None:
        return
    s = db.get(Site, site_id)
    if s is None or s.customer_id != customer.id:
        raise field_error("site_id", "Site does not belong to this customer")
    if s.status != ActiveStatus.ACTIVE:
        raise field_error("site_id", "Select an active site")


def _check_shift(db: Session, shift_id: int | None, customer: Customer, current: int | None = None) -> None:
    if shift_id is None or shift_id == current:
        return
    sh = db.get(ShiftDefinition, shift_id)
    if sh is None or sh.customer_id != customer.id or sh.status != ActiveStatus.ACTIVE:
        raise field_error("shift_id", "Select an active shift of this customer")


@router.get("")
def list_employees(
    q: str | None = None, customer_id: int | None = None, site_id: int | None = None,
    gender: str | None = None, status: ActiveStatus | None = None, vendor_id: int | None = None,
    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("employee:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = []
    if (mine := operator_customer(user)) is not None:
        cond.append(Employee.customer_id == mine)
    if not scope.is_global:
        cond.append(Employee.vendor_id == scope.vendor_id)
    elif vendor_id:
        cond.append(Employee.vendor_id == vendor_id)
    if customer_id:
        cond.append(Employee.customer_id == customer_id)
    if site_id:
        cond.append(Employee.site_id == site_id)
    if gender:
        cond.append(Employee.gender == gender)
    if status:
        cond.append(Employee.status == status)
    if q:
        like = f"%{q}%"
        cond.append(or_(Employee.first_name.ilike(like), Employee.last_name.ilike(like),
                        Employee.employee_code.ilike(like), Employee.mobile.ilike(like)))
    total = db.scalar(select(func.count()).select_from(Employee).where(*cond))
    rows = db.scalars(select(Employee).where(*cond).order_by(Employee.first_name, Employee.id).limit(limit).offset(offset)).all()
    cust, sites = _names(db, rows) if rows else ({}, {})
    return {"total": total, "items": [_out(e, cust, sites) for e in rows]}


@router.post("", response_model=EmployeeOut, status_code=201)
def create_employee(body: EmployeeIn, actor: User = Depends(require_permission("employee:create")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    mine = require_operator_customer(actor)
    if mine is not None:  # an Operator always adds for their own customer, whatever was sent
        body = body.model_copy(update={"customer_id": mine})
    if body.customer_id is None:
        raise field_error("customer_id", "Customer is required")
    cust = get_scoped(db, scope, Customer, body.customer_id)
    if cust.status != ActiveStatus.ACTIVE:
        raise field_error("customer_id", "Select an active customer")
    _check_site(db, body.site_id, cust)
    _check_shift(db, body.shift_id, cust)
    ensure_unique(db, Employee, "employee_code", body.employee_code, customer_id=cust.id)
    e = Employee(**body.model_dump(exclude={"customer_id", "email"}), customer_id=cust.id, vendor_id=cust.vendor_id,
                 email=str(body.email) if body.email else None)
    db.add(e)
    db.flush()
    audit.record(db, "employee.created", actor, entity_type="employee", entity_id=e.id, vendor_id=e.vendor_id)
    db.commit()
    return _out(e, *_names(db, [e]))


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: int, user: User = Depends(require_permission("employee:read")),
                 scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    e = get_scoped(db, scope, Employee, employee_id)
    ensure_operator_customer(user, e.customer_id)
    return _out(e, *_names(db, [e]))


@router.put("/{employee_id}", response_model=EmployeeOut)
def update_employee(employee_id: int, body: EmployeeIn, actor: User = Depends(require_permission("employee:create")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    e = get_scoped(db, scope, Employee, employee_id)
    ensure_operator_customer(actor, e.customer_id)
    cust = db.get(Customer, e.customer_id)
    if body.customer_id is not None and body.customer_id != e.customer_id:
        raise field_error("customer_id", "An employee cannot be moved to another customer")
    if body.site_id != e.site_id:
        _check_site(db, body.site_id, cust)
    _check_shift(db, body.shift_id, cust, current=e.shift_id)
    ensure_unique(db, Employee, "employee_code", body.employee_code, exclude_id=e.id, customer_id=e.customer_id)
    for k, v in body.model_dump(exclude={"customer_id", "email"}).items():
        setattr(e, k, v)
    e.email = str(body.email) if body.email else None
    audit.record(db, "employee.updated", actor, entity_type="employee", entity_id=e.id, vendor_id=e.vendor_id)
    db.commit()
    return _out(e, *_names(db, [e]))


@router.patch("/{employee_id}/status", response_model=EmployeeOut)
def set_employee_status(employee_id: int, body: StatusBody, actor: User = Depends(require_permission("employee:write")),
                        scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    e = get_scoped(db, scope, Employee, employee_id)
    e.status = body.status
    audit.record(db, f"employee.{'activated' if body.status == ActiveStatus.ACTIVE else 'deactivated'}", actor,
                 entity_type="employee", entity_id=e.id, vendor_id=e.vendor_id)
    db.commit()
    return _out(e, *_names(db, [e]))
