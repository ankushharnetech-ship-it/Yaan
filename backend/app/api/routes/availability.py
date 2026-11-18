"""GET /api/drivers/availability and /api/vehicles/availability (registered before the /{id} routes)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import field_error
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import Employee, LookupValue, User, Vendor
from app.services import availability as avail

router = APIRouter(tags=["availability"])


def _window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if start.tzinfo is None or end.tzinfo is None:
        raise field_error("start", "Include a timezone offset in start and end")
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    if end <= start:
        raise field_error("end", "End must be after start")
    return start, end


def _vendor(scope: VendorScope, vendor_id: int | None, db: Session) -> int:
    if not scope.is_global:
        return scope.vendor_id  # type: ignore[return-value]
    if vendor_id is None or db.get(Vendor, vendor_id) is None:
        raise field_error("vendor_id", "Vendor is required")
    return vendor_id


@router.get("/drivers/availability")
def driver_availability(
    start: datetime, end: datetime, vendor_id: int | None = None, exclude_trip_id: int | None = None,
    _: User = Depends(require_permission("availability:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    s, e = _window(start, end)
    rows = avail.driver_availability(db, _vendor(scope, vendor_id, db), s, e, exclude_trip_id)
    return {"items": [
        {"id": a.resource.id, "code": a.resource.code, "name": f"{a.resource.first_name} {a.resource.last_name}",
         "contact_number": a.resource.contact_number, "gender": a.resource.gender,
         "default_vehicle_id": a.resource.default_vehicle_id,
         "available": a.available, "reasons": a.reasons} for a in rows]}


@router.get("/vehicles/availability")
def vehicle_availability(
    start: datetime, end: datetime, employee_ids: str = Query(..., description="comma separated passenger ids"),
    vendor_id: int | None = None, exclude_trip_id: int | None = None,
    _: User = Depends(require_permission("availability:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    s, e = _window(start, end)
    vid = _vendor(scope, vendor_id, db)
    try:
        ids = sorted({int(x) for x in employee_ids.split(",") if x.strip()})
    except ValueError:
        raise field_error("employee_ids", "Invalid passenger list")
    if not ids:
        raise field_error("employee_ids", "Select at least one passenger")
    emps = db.scalars(select(Employee).where(Employee.id.in_(ids), Employee.vendor_id == vid)).all()
    if len(emps) != len(ids):
        raise field_error("employee_ids", "Unknown passenger in list")
    escort, needed = avail.required_capacity(len(emps), any(x.gender == "female" for x in emps))
    types = dict(db.execute(select(LookupValue.id, LookupValue.label).where(LookupValue.category == "vehicle_type")).all())
    rows = avail.vehicle_availability(db, vid, s, e, needed, exclude_trip_id)
    return {
        "passenger_count": len(emps), "escort_required": escort, "required_capacity": needed,
        "items": [{"id": a.resource.id, "vehicle_number": a.resource.vehicle_number, "model": a.resource.model,
                   "vehicle_type": types.get(a.resource.vehicle_type_id), "capacity": a.resource.capacity,
                   "available": a.available, "reasons": a.reasons} for a in rows],
    }
