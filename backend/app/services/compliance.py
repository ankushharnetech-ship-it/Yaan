"""Compliance status rules (spec 17).

A document is *valid through* its expiry date. Relative to today (business timezone):
  expired  -> expiry date is in the past
  expiring -> expires within the warning window (default 30 days, configurable per vendor)
  valid    -> anything later
Retired (inactive) items are ignored. A driver/vehicle is
  non_compliant  if any active document has expired,
  expiring       if none expired but some expire within the window,
  compliant      if it has documents and all are valid,
  no_documents   if nothing has been recorded for it.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import local_date
from app.models import ActiveStatus, ComplianceItem, Driver, LookupValue, Vehicle
from app.services import app_settings


def today() -> date:
    return local_date(datetime.now(timezone.utc))


def classify(expiry: date, now: date, warn_days: int) -> str:
    days = (expiry - now).days
    return "expired" if days < 0 else "expiring" if days <= warn_days else "valid"


@dataclass
class Row:
    item: ComplianceItem
    state: str
    days_left: int


def load(db: Session, subject: str, vendor_id: int | None, driver_id: int | None = None, *, doc_type_id: int | None = None,
         subject_id: int | None = None, include_retired: bool = False) -> list[Row]:
    q = select(ComplianceItem).where(ComplianceItem.subject_type == subject)
    if not include_retired:
        q = q.where(ComplianceItem.status == ActiveStatus.ACTIVE)
    if vendor_id is not None:
        q = q.where(ComplianceItem.vendor_id == vendor_id)
    if driver_id is not None:
        q = q.where(ComplianceItem.driver_id == driver_id)
    if doc_type_id:
        q = q.where(ComplianceItem.doc_type_id == doc_type_id)
    if subject_id:
        q = q.where((ComplianceItem.driver_id if subject == "driver" else ComplianceItem.vehicle_id) == subject_id)
    now, warn_cache, rows = today(), {}, []
    for it in db.scalars(q.order_by(ComplianceItem.expiry_date, ComplianceItem.id)):
        if it.vendor_id not in warn_cache:
            warn_cache[it.vendor_id] = app_settings.get_int(db, "compliance_expiry_warning_days", it.vendor_id)
        rows.append(Row(it, classify(it.expiry_date, now, warn_cache[it.vendor_id]), (it.expiry_date - now).days))
    return rows


def subject_rollup(db: Session, subject: str, rows: list[Row], vendor_id: int | None, driver_id: int | None,
                   subject_id: int | None = None) -> list[dict]:
    """One entry per active driver/vehicle in scope, with its overall state."""
    model = Driver if subject == "driver" else Vehicle
    q = select(model).where(model.status == ActiveStatus.ACTIVE)
    if vendor_id is not None:
        q = q.where(model.vendor_id == vendor_id)
    if driver_id is not None:
        q = q.where(model.id == driver_id)
    if subject_id:
        q = q.where(model.id == subject_id)
    by: dict[int, list[Row]] = {}
    for r in rows:
        by.setdefault(r.item.driver_id if subject == "driver" else r.item.vehicle_id, []).append(r)
    out = []
    for s in db.scalars(q.order_by(model.id)):
        rs = by.get(s.id, [])
        states = {r.state for r in rs}
        state = ("no_documents" if not rs else "non_compliant" if "expired" in states
                 else "expiring" if "expiring" in states else "compliant")
        out.append({"id": s.id, "name": f"{s.first_name} {s.last_name}" if subject == "driver" else s.vehicle_number,
                    "code": s.code, "state": state, "documents": len(rs),
                    "expired": sum(r.state == "expired" for r in rs), "expiring": sum(r.state == "expiring" for r in rs)})
    return out


def doc_type_names(db: Session, category: str) -> dict[int, str]:
    return dict(db.execute(select(LookupValue.id, LookupValue.label).where(LookupValue.category == category)).all())
