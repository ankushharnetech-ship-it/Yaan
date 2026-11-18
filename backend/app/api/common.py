"""Helpers shared by master-data routers (vendor scoping, uniqueness, pagination)."""
import re
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import VendorScope
from app.models import ActiveStatus, LookupValue, Role, User, Vendor

Gender = Literal["male", "female", "other"]
_MOBILE = re.compile(r"^\+?[0-9][0-9 \-]{6,18}$")


def field_error(field: str, msg: str, code: int = 422) -> HTTPException:
    return HTTPException(code, detail=[{"loc": ["body", field], "msg": msg}])


def validate_mobile(v: str | None) -> str | None:
    if v is None or v == "":
        return None
    if not _MOBILE.match(v.strip()):
        raise ValueError("Enter a valid phone number")
    return v.strip()


class Body(BaseModel):
    """Base request model: trims strings, turns blank strings into None."""

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        return None if isinstance(v, str) and v == "" else v


class StatusBody(BaseModel):
    status: ActiveStatus


def resolve_vendor_id(scope: VendorScope, requested: int | None, db: Session) -> int:
    """Vendor-scoped callers always act in their own vendor. Super Admin must name one."""
    if scope.is_global:
        if requested is None:
            raise field_error("vendor_id", "Vendor is required")
        v = db.get(Vendor, requested)
        if v is None or v.status != ActiveStatus.ACTIVE:
            raise field_error("vendor_id", "Select an active vendor")
        return requested
    return scope.vendor_id  # type: ignore[return-value]


def get_scoped(db: Session, scope: VendorScope, model, record_id: int, vendor_field: str = "vendor_id"):
    """Fetch by id; 404 (never 403) if missing or outside the caller's vendor scope."""
    obj = db.get(model, record_id)
    if obj is None:
        raise HTTPException(404, "Not found")
    scope.ensure(getattr(obj, vendor_field))
    return obj


def ensure_unique(db: Session, model, field: str, value, *, exclude_id: int | None = None, **same: object) -> None:
    col = getattr(model, field)
    q = select(model.id).where(func.lower(col) == str(value).lower() if isinstance(value, str) else col == value)
    for k, v in same.items():
        q = q.where(getattr(model, k) == v)
    if exclude_id:
        q = q.where(model.id != exclude_id)
    if db.scalar(q.limit(1)):
        raise field_error(field, "Already in use")


def check_lookup(db: Session, lookup_id: int | None, category: str, field: str, required: bool = False) -> None:
    if lookup_id is None:
        if required:
            raise field_error(field, "This field is required")
        return
    row = db.get(LookupValue, lookup_id)
    if row is None or row.category != category or not row.is_active:
        raise field_error(field, "Invalid selection")


def page(db: Session, stmt, count_stmt, limit: int, offset: int, order):
    total = db.scalar(count_stmt)
    return total, db.scalars(stmt.order_by(*order).limit(limit).offset(offset)).all()


def operator_customer(user: User) -> int | None:
    """The customer an Operator is tagged to (None for every other role, and for an Operator not yet tagged)."""
    return user.customer_id if user.role == Role.OPERATOR else None


def require_operator_customer(user: User) -> int | None:
    """For creating records: an Operator must be tagged to a customer first. Other roles return None (they pick one)."""
    if user.role != Role.OPERATOR:
        return None
    if user.customer_id is None:
        raise HTTPException(409, "Your account is not linked to a customer yet. Ask your administrator to assign one.")
    return user.customer_id


def ensure_operator_customer(user: User, customer_id: int) -> None:
    """404 when a tagged Operator reaches for another customer's record."""
    mine = operator_customer(user)
    if mine is not None and customer_id != mine:
        raise HTTPException(404, "Not found")
