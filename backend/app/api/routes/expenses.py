"""Expenses (vehicle, fuel, maintenance…). Anyone can record one; visibility follows the confirmed rules:
  * Driver / Operator: only the expenses they entered.
  * Vendor Admin: every expense of their vendor.   * Super Admin: every vendor.
Summaries: Super Admin (all vendors) and Vendor Admin (own vendor) only.
The person who entered an expense may edit/void it for EXPENSE_EDIT_WINDOW_HOURS; admins always. Nothing is deleted."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.common import Body, check_lookup, field_error, resolve_vendor_id
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.core.config import get_settings
from app.core.permissions import has_permission
from app.core.timeutil import local_date
from app.db.session import get_db
from app.models import ActiveStatus, Driver, Expense, LookupValue, Role, User, Vehicle, Vendor
from app.services import analytics as an, audit

router = APIRouter(prefix="/expenses", tags=["expenses"])

PAYMENT_METHODS = {"cash": "Cash", "upi": "UPI", "card": "Card", "bank_transfer": "Bank transfer",
                   "fuel_card": "Company fuel card", "other": "Other"}
Payment = Literal["cash", "upi", "card", "bank_transfer", "fuel_card", "other"]


class ExpenseIn(Body):
    vendor_id: int | None = None  # Super Admin only; everyone else is pinned to their own vendor
    expense_date: date
    category_id: int
    amount: Decimal = Field(gt=0, le=10_000_000, decimal_places=2)
    payment_method: Payment
    description: str | None = Field(default=None, max_length=1000)
    vehicle_id: int | None = None
    driver_id: int | None = None

    @field_validator("expense_date")
    @classmethod
    def _not_future(cls, v: date):
        if v > local_date(datetime.now(timezone.utc)):
            raise ValueError("An expense cannot be dated in the future")
        return v


class VoidIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


# ------------------------------------------------------------------ rules
def _can_manage(user: User) -> bool:
    return has_permission(user.role, "expense:manage")


def _in_window(e: Expense) -> bool:
    return datetime.now(timezone.utc) - e.created_at <= timedelta(hours=get_settings().expense_edit_window_hours)


def _can_change(user: User, scope: VendorScope, e: Expense) -> bool:
    if e.status != "recorded":
        return False
    if _can_manage(user):
        return scope.is_global or e.vendor_id == scope.vendor_id
    return e.created_by == user.id and _in_window(e)


def _visible(user: User, scope: VendorScope) -> list:
    if _can_manage(user):
        return [] if scope.is_global else [Expense.vendor_id == scope.vendor_id]
    return [Expense.created_by == user.id]


def _get(db: Session, user: User, scope: VendorScope, expense_id: int) -> Expense:
    e = db.scalar(select(Expense).where(Expense.id == expense_id, *_visible(user, scope)))
    if e is None:
        raise HTTPException(404, "Not found")
    return e


def _money(v) -> float:
    return round(float(v or 0), 2)


def _out(db: Session, rows: list[Expense], user: User, scope: VendorScope) -> list[dict]:
    if not rows:
        return []
    ids = lambda f: {getattr(r, f) for r in rows if getattr(r, f)}  # noqa: E731
    people = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids("created_by") | ids("voided_by"))))}
    cats = dict(db.execute(select(LookupValue.id, LookupValue.label).where(LookupValue.category == "expense_category")).all())
    veh = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(ids("vehicle_id"))))} if ids("vehicle_id") else {}
    drv = {d.id: d for d in db.scalars(select(Driver).where(Driver.id.in_(ids("driver_id"))))} if ids("driver_id") else {}
    ven = dict(db.execute(select(Vendor.id, Vendor.name).where(Vendor.id.in_(ids("vendor_id")))).all())
    name = lambda u: f"{u.first_name} {u.last_name}" if u else None  # noqa: E731
    out = []
    for e in rows:
        by, vb, d, v = people.get(e.created_by), people.get(e.voided_by), drv.get(e.driver_id), veh.get(e.vehicle_id)
        mutable = _can_change(user, scope, e)
        out.append({
            "id": e.id, "code": e.code, "vendor_id": e.vendor_id, "vendor_name": ven.get(e.vendor_id),
            "expense_date": e.expense_date.isoformat(), "category_id": e.category_id, "category": cats.get(e.category_id),
            "amount": _money(e.amount), "payment_method": e.payment_method,
            "payment_method_label": PAYMENT_METHODS.get(e.payment_method, e.payment_method), "description": e.description,
            "vehicle_id": e.vehicle_id, "vehicle_number": v.vehicle_number if v else None,
            "driver_id": e.driver_id, "driver_name": f"{d.first_name} {d.last_name}" if d else None,
            "entered_by_id": e.created_by, "entered_by": name(by), "entered_by_role": by.role.value if by else None,
            "created_at": e.created_at.astimezone(timezone.utc).isoformat(), "status": e.status,
            "void_reason": e.void_reason, "voided_by": name(vb),
            "voided_at": e.voided_at.astimezone(timezone.utc).isoformat() if e.voided_at else None,
            "can_edit": mutable, "can_void": mutable,
        })
    return out


def _validate_links(db: Session, user: User, vendor_id: int, body: ExpenseIn) -> int | None:
    """Checks category/vehicle/driver belong together; returns the driver_id to store."""
    check_lookup(db, body.category_id, "expense_category", "category_id", required=True)
    if body.vehicle_id is not None:
        v = db.get(Vehicle, body.vehicle_id)
        if v is None or v.vendor_id != vendor_id:
            raise field_error("vehicle_id", "Select a vehicle of this vendor")
    driver_id = body.driver_id
    if user.role == Role.DRIVER:  # drivers can only attribute expenses to themselves
        driver_id = user.driver_id
    elif driver_id is not None:
        d = db.get(Driver, driver_id)
        if d is None or d.vendor_id != vendor_id:
            raise field_error("driver_id", "Select a driver of this vendor")
    return driver_id


# ------------------------------------------------------------------ pick-lists for the form
@router.get("/options")
def options(vendor_id: int | None = None, user: User = Depends(require_permission("expense:create")),
            scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    vid = scope.vendor_id if not scope.is_global else vendor_id
    cats = db.scalars(select(LookupValue).where(LookupValue.category == "expense_category", LookupValue.is_active)
                      .order_by(LookupValue.sort_order)).all()
    vehicles, drivers = [], []
    if vid is not None:
        vehicles = [{"id": v.id, "label": f"{v.vehicle_number} ({v.model})"} for v in db.scalars(
            select(Vehicle).where(Vehicle.vendor_id == vid).order_by(Vehicle.vehicle_number))]
        dq = select(Driver).where(Driver.vendor_id == vid).order_by(Driver.first_name)
        if user.role == Role.DRIVER:
            dq = dq.where(Driver.id == (user.driver_id or -1))
        drivers = [{"id": d.id, "label": f"{d.first_name} {d.last_name}"} for d in db.scalars(dq)]
    return {"categories": [{"id": c.id, "label": c.label} for c in cats],
            "payment_methods": [{"value": k, "label": v} for k, v in PAYMENT_METHODS.items()],
            "vehicles": vehicles, "drivers": drivers, "own_driver_id": user.driver_id if user.role == Role.DRIVER else None}


# ------------------------------------------------------------------ summary (Super Admin / Vendor Admin)
@router.get("/summary")
def summary(range: str = Query("this_month"), date_from: date | None = None, date_to: date | None = None,
            vendor_id: int | None = None, user: User = Depends(require_permission("expense:summary")),
            scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    first, last, label = an.resolve_dates(range, date_from, date_to)
    vid = scope.vendor_id if not scope.is_global else vendor_id
    base = [Expense.status == "recorded"] + ([] if vid is None else [Expense.vendor_id == vid])
    cond = base + [Expense.expense_date >= first, Expense.expense_date <= last]
    amt = func.coalesce(func.sum(Expense.amount), 0)

    total, count = db.execute(select(amt, func.count()).where(*cond)).one()
    days = (last - first).days + 1
    p_last = first - timedelta(days=1)
    p_first = p_last - timedelta(days=days - 1)
    prev = db.scalar(select(amt).where(*base, Expense.expense_date >= p_first, Expense.expense_date <= p_last))

    def group(col, *joins, limit=None, label_col=None):
        q = select(label_col if label_col is not None else col, amt, func.count()).select_from(Expense)
        for j in joins:
            q = q.join(*j)
        q = q.where(*cond).group_by(label_col if label_col is not None else col).order_by(amt.desc())
        if limit:
            q = q.limit(limit)
        return [{"name": n or "—", "amount": _money(a), "count": c} for n, a, c in db.execute(q).all()]

    monthly = days > 62
    bucket = func.date_trunc("month" if monthly else "day", Expense.expense_date)
    trend = [{"label": d.date().isoformat()[:7] if monthly else d.date().isoformat(), "amount": _money(a)}
             for d, a in db.execute(select(bucket, amt).where(*cond).group_by(bucket).order_by(bucket)).all()]
    person = func.concat(User.first_name, " ", User.last_name)
    people = [{"name": n, "role": r.value, "amount": _money(a), "count": c} for n, r, a, c in db.execute(
        select(person, User.role, amt, func.count()).select_from(Expense).join(User, User.id == Expense.created_by)
        .where(*cond).group_by(User.id, person, User.role).order_by(amt.desc()).limit(8)).all()]
    voided = db.scalar(select(func.count()).where(Expense.status == "voided", Expense.expense_date >= first,
                                                  Expense.expense_date <= last, *([] if vid is None else [Expense.vendor_id == vid])))
    return {
        "range_label": label, "vendor_id": vid, "first": first.isoformat(), "last": last.isoformat(),
        "total": _money(total), "count": count, "average": _money(total / count) if count else 0.0,
        "previous_total": _money(prev), "change_pct": round(100 * (float(total) - float(prev)) / float(prev), 1) if prev else None,
        "voided_count": voided,
        "by_category": group(None, (LookupValue, LookupValue.id == Expense.category_id), label_col=LookupValue.label),
        "by_vehicle": group(None, (Vehicle, Vehicle.id == Expense.vehicle_id), limit=8, label_col=Vehicle.vehicle_number),
        "by_payment": [{"name": PAYMENT_METHODS.get(r["name"], r["name"]), "amount": r["amount"], "count": r["count"]}
                       for r in group(Expense.payment_method)],
        "by_person": people, "trend": trend, "trend_unit": "month" if monthly else "day",
        "by_vendor": group(None, (Vendor, Vendor.id == Expense.vendor_id), label_col=Vendor.name) if scope.is_global else [],
        "without_vehicle": _money(db.scalar(select(amt).where(*cond, Expense.vehicle_id.is_(None)))),
    }


# ------------------------------------------------------------------ list / CRUD
@router.get("")
def list_expenses(
    q: str | None = None, category_id: int | None = None, vehicle_id: int | None = None, driver_id: int | None = None,
    entered_by: int | None = None, payment_method: Payment | None = None, status: Literal["recorded", "voided"] | None = None,
    vendor_id: int | None = None, date_from: date | None = None, date_to: date | None = None,
    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("expense:create")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = _visible(user, scope)
    if scope.is_global and vendor_id:
        cond.append(Expense.vendor_id == vendor_id)
    for col, val in ((Expense.category_id, category_id), (Expense.vehicle_id, vehicle_id), (Expense.driver_id, driver_id),
                     (Expense.payment_method, payment_method), (Expense.status, status)):
        if val is not None:
            cond.append(col == val)
    if entered_by and _can_manage(user):
        cond.append(Expense.created_by == entered_by)
    if date_from:
        cond.append(Expense.expense_date >= date_from)
    if date_to:
        cond.append(Expense.expense_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        cond.append(or_(Expense.description.ilike(like), Expense.code.ilike(like)))
    total = db.scalar(select(func.count()).select_from(Expense).where(*cond))
    total_amount = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(*cond, Expense.status == "recorded"))
    rows = db.scalars(select(Expense).where(*cond).order_by(Expense.expense_date.desc(), Expense.id.desc())
                      .limit(limit).offset(offset)).all()
    return {"total": total, "total_amount": _money(total_amount), "items": _out(db, list(rows), user, scope)}


@router.post("", status_code=201)
def create_expense(body: ExpenseIn, actor: User = Depends(require_permission("expense:create")),
                   scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    vid = resolve_vendor_id(scope, body.vendor_id, db)
    driver_id = _validate_links(db, actor, vid, body)
    e = Expense(vendor_id=vid, expense_date=body.expense_date, category_id=body.category_id, amount=body.amount,
                payment_method=body.payment_method, description=body.description, vehicle_id=body.vehicle_id,
                driver_id=driver_id, created_by=actor.id)
    db.add(e)
    db.flush()
    e.code = f"EXP-{e.id:06d}"
    audit.record(db, "expense.created", actor, entity_type="expense", entity_id=e.id, vendor_id=vid,
                 detail={"code": e.code, "amount": str(e.amount)})
    db.commit()
    db.refresh(e)
    return _out(db, [e], actor, scope)[0]


@router.get("/{expense_id}")
def get_expense(expense_id: int, user: User = Depends(require_permission("expense:create")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    return _out(db, [_get(db, user, scope, expense_id)], user, scope)[0]


@router.put("/{expense_id}")
def update_expense(expense_id: int, body: ExpenseIn, actor: User = Depends(require_permission("expense:create")),
                   scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    e = _get(db, actor, scope, expense_id)
    if e.status == "voided":
        raise HTTPException(409, "A voided expense cannot be edited")
    if not _can_change(actor, scope, e):
        raise HTTPException(403, f"This expense can no longer be edited by you "
                                 f"(the {get_settings().expense_edit_window_hours}-hour edit window has passed). Ask a Vendor Admin.")
    driver_id = _validate_links(db, actor, e.vendor_id, body)
    before = {"amount": str(e.amount), "category_id": e.category_id, "date": e.expense_date.isoformat()}
    e.expense_date, e.category_id, e.amount, e.payment_method = body.expense_date, body.category_id, body.amount, body.payment_method
    e.description, e.vehicle_id, e.driver_id = body.description, body.vehicle_id, driver_id
    audit.record(db, "expense.updated", actor, entity_type="expense", entity_id=e.id, vendor_id=e.vendor_id,
                 detail={"code": e.code, "before": before, "after": {"amount": str(e.amount), "category_id": e.category_id,
                                                                     "date": e.expense_date.isoformat()}})
    db.commit()
    db.refresh(e)
    return _out(db, [e], actor, scope)[0]


@router.post("/{expense_id}/void")
def void_expense(expense_id: int, body: VoidIn, actor: User = Depends(require_permission("expense:create")),
                 scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    e = _get(db, actor, scope, expense_id)
    if e.status == "voided":
        raise HTTPException(409, "This expense is already voided")
    if not _can_change(actor, scope, e):
        raise HTTPException(403, "This expense can no longer be voided by you. Ask a Vendor Admin.")
    e.status, e.void_reason, e.voided_by, e.voided_at = "voided", body.reason.strip(), actor.id, datetime.now(timezone.utc)
    audit.record(db, "expense.voided", actor, entity_type="expense", entity_id=e.id, vendor_id=e.vendor_id,
                 detail={"code": e.code, "reason": e.void_reason})
    db.commit()
    db.refresh(e)
    return _out(db, [e], actor, scope)[0]
