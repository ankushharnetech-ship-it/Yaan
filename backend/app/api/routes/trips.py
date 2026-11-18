from datetime import date, datetime, time, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import Body, check_lookup, field_error, operator_customer, require_operator_customer
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.core.config import get_settings
from app.core.permissions import has_permission
from app.core.timeutil import tz
from app.db.session import get_db
from app.models import (
    ActiveStatus, Customer, Driver, EmailLog, Employee, LookupValue, Role, ShiftDefinition, Site, Trip, TripAssignment,
    SmsLog, TripPassenger, TripStatus, TripStatusHistory, User, Vehicle,
)
from app.services import audit, availability as avail, geocode, notifications, otp

router = APIRouter(prefix="/trips", tags=["trips"])

OPEN = (TripStatus.SCHEDULED, TripStatus.ASSIGNED, TripStatus.ACCEPTED)  # can still be edited / cancelled


# ------------------------------------------------------------------ schemas
class TripIn(Body):
    customer_id: int | None = None  # required on create; cannot change later
    site_id: int
    trip_type_id: int
    shift_id: int | None = None
    scheduled_start: datetime
    scheduled_end: datetime  # required: needed for the availability check
    route_name: str | None = Field(default=None, max_length=200)
    special_instructions: str | None = None
    pickup_address: str = Field(min_length=1)
    pickup_latitude: float | None = Field(default=None, ge=-90, le=90)
    pickup_longitude: float | None = Field(default=None, ge=-180, le=180)
    drop_address: str = Field(min_length=1)
    drop_latitude: float | None = Field(default=None, ge=-90, le=90)
    drop_longitude: float | None = Field(default=None, ge=-180, le=180)
    employee_ids: list[int] = Field(min_length=1, max_length=60)  # ordered = stop order
    driver_id: int | None = None  # required on create; optional on edit (None keeps current)
    vehicle_id: int | None = None

    @field_validator("scheduled_start", "scheduled_end")
    @classmethod
    def _aware(cls, v: datetime):
        if v.tzinfo is None:
            raise ValueError("Include a timezone offset (e.g. 2026-03-01T09:00:00+05:30)")
        return v.astimezone(timezone.utc)

    @field_validator("employee_ids")
    @classmethod
    def _unique(cls, v: list[int]):
        if len(set(v)) != len(v):
            raise ValueError("A passenger can only be added once")
        return v


class AssignIn(BaseModel):
    driver_id: int | None = None
    vehicle_id: int | None = None


class CancelIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class DriverStatusIn(BaseModel):
    status: Literal["accepted", "started", "completed"]


# ------------------------------------------------------------------ presentation
def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _maps(db: Session, trips: list[Trip]) -> dict:
    ids = lambda f: {getattr(t, f) for t in trips if getattr(t, f)}  # noqa: E731
    one = lambda stmt: dict(db.execute(stmt).all())  # noqa: E731
    users = ids("created_by") | ids("cancelled_by")
    drivers = {d.id: d for d in db.scalars(select(Driver).where(Driver.id.in_(ids("driver_id"))))} if trips else {}
    vehicles = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(ids("vehicle_id"))))} if trips else {}
    return {
        "customer": one(select(Customer.id, Customer.name).where(Customer.id.in_(ids("customer_id")))) if trips else {},
        "site": one(select(Site.id, Site.name).where(Site.id.in_(ids("site_id")))) if trips else {},
        "shift": one(select(ShiftDefinition.id, ShiftDefinition.name).where(ShiftDefinition.id.in_(ids("shift_id")))) if ids("shift_id") else {},
        "type": one(select(LookupValue.id, LookupValue.label).where(LookupValue.id.in_(ids("trip_type_id")))) if trips else {},
        "user": one(select(User.id, func.concat(User.first_name, " ", User.last_name)).where(User.id.in_(users))) if users else {},
        "driver": drivers, "vehicle": vehicles,
        "pax": _passengers(db, [t.id for t in trips]),
        "sms": _sms_summary(db, [t.id for t in trips]),
        "notify": _notify_summary(db, [t.id for t in trips]),
    }


def _sms_summary(db: Session, trip_ids: list[int]) -> dict[int, str]:
    """failed > pending > delivered/sent per trip; absent when no SMS were generated."""
    out: dict[int, set[str]] = {}
    if trip_ids:
        for tid, st in db.execute(select(SmsLog.trip_id, SmsLog.status).where(SmsLog.trip_id.in_(trip_ids)).distinct()):
            out.setdefault(tid, set()).add(st)
    pick = lambda s: "failed" if "failed" in s else "pending" if "pending" in s else "sent"  # noqa: E731
    return {tid: pick(s) for tid, s in out.items()}


def _notify_summary(db: Session, trip_ids: list[int]) -> dict[int, str]:
    """Same idea across both channels."""
    out: dict[int, set[str]] = {}
    if trip_ids:
        for model in (SmsLog, EmailLog):
            for tid, st in db.execute(select(model.trip_id, model.status).where(model.trip_id.in_(trip_ids)).distinct()):
                out.setdefault(tid, set()).add(st)
    pick = lambda s: "failed" if "failed" in s else "pending" if "pending" in s else "sent"  # noqa: E731
    return {tid: pick(s) for tid, s in out.items()}


def drop_status(p: TripPassenger) -> str:
    """none (no OTP yet: the trip is still a request) | pending | verified | not_dropped"""
    if p.otp_verified_at:
        return "verified"
    if p.not_dropped_at:
        return "not_dropped"
    return "pending" if p.otp_seed else "none"


def _passengers(db: Session, trip_ids: list[int]) -> dict[int, list[TripPassenger]]:
    out: dict[int, list[TripPassenger]] = {}
    if trip_ids:
        for p in db.scalars(select(TripPassenger).where(TripPassenger.trip_id.in_(trip_ids)).order_by(TripPassenger.sequence)):
            out.setdefault(p.trip_id, []).append(p)
    return out


def _serialize(t: Trip, m: dict, viewer: User) -> dict:
    d, v = m["driver"].get(t.driver_id), m["vehicle"].get(t.vehicle_id)
    is_driver = viewer.role == Role.DRIVER
    # The OTP code itself is shown to exactly one kind of viewer: the Operator who requested this trip, while it is live
    # and the employee has not yet been dropped. Drivers, Vendor Admins and Super Admins never receive it.
    may_see_otp = (viewer.role == Role.OPERATOR and viewer.id == t.created_by
                   and t.status in (TripStatus.ASSIGNED, TripStatus.ACCEPTED, TripStatus.STARTED))
    max_tries = get_settings().otp_max_attempts
    pax = []
    for p in m["pax"].get(t.id, []):
        entry = {"employee_id": p.employee_id, "sequence": p.sequence, "name": p.name, "address": p.address,
                 **({} if is_driver else {"mobile": p.mobile, "gender": p.gender}),
                 "drop_status": drop_status(p), "otp_locked": p.otp_attempts >= max_tries and drop_status(p) == "pending",
                 "otp_verified_at": _iso(p.otp_verified_at), "not_dropped_reason": p.not_dropped_reason,
                 "not_dropped_at": _iso(p.not_dropped_at)}
        if may_see_otp and p.otp_seed and drop_status(p) == "pending":
            entry["otp"] = otp.code(p.otp_seed, t.id, p.employee_id)
        pax.append(entry)
    return {
        "id": t.id, "code": t.code, "status": t.status.value, "vendor_id": t.vendor_id,
        "customer_id": t.customer_id, "customer_name": m["customer"].get(t.customer_id),
        "site_id": t.site_id, "site_name": m["site"].get(t.site_id),
        "trip_type_id": t.trip_type_id, "trip_type": m["type"].get(t.trip_type_id),
        "shift_id": t.shift_id, "shift_name": m["shift"].get(t.shift_id),
        "scheduled_start": _iso(t.scheduled_start), "scheduled_end": _iso(t.scheduled_end),
        "route_name": t.route_name, "special_instructions": t.special_instructions,
        "pickup_address": t.pickup_address, "pickup_latitude": t.pickup_latitude, "pickup_longitude": t.pickup_longitude,
        "drop_address": t.drop_address, "drop_latitude": t.drop_latitude, "drop_longitude": t.drop_longitude,
        "passenger_count": t.passenger_count, "escort_required": t.escort_required, "required_capacity": t.required_capacity,
        "passengers": pax,
        "sms_status": None if is_driver else m["sms"].get(t.id),
        "notify_status": None if is_driver else m["notify"].get(t.id),  # SMS and Email combined: failed > pending > sent
        "drops_resolved": sum(1 for p in m["pax"].get(t.id, []) if drop_status(p) in ("verified", "not_dropped")),
        "created_by_id": t.created_by,
        # what THIS viewer may do next (the API enforces it; the UI uses it to show the right buttons)
        "can_assign": has_permission(viewer.role, "trip:assign") and t.status in OPEN,
        "can_edit": (not is_driver and has_permission(viewer.role, "trip:edit") and t.status not in (TripStatus.COMPLETED, TripStatus.CANCELLED)
                     and (t.status == TripStatus.SCHEDULED or has_permission(viewer.role, "trip:assign"))),
        "can_cancel": (not is_driver and has_permission(viewer.role, "trip:cancel") and t.status in OPEN
                       and (t.status == TripStatus.SCHEDULED or has_permission(viewer.role, "trip:assign"))),
        "driver_id": t.driver_id,
        "driver_name": f"{d.first_name} {d.last_name}" if d else None,
        "driver_contact": None if is_driver or not d else d.contact_number,
        "vehicle_id": t.vehicle_id, "vehicle_number": v.vehicle_number if v else None,
        "vehicle_capacity": v.capacity if v else None,
        "created_by": m["user"].get(t.created_by), "created_at": _iso(t.created_at),
        "accepted_at": _iso(t.accepted_at), "started_at": _iso(t.started_at), "completed_at": _iso(t.completed_at),
        "cancelled_at": _iso(t.cancelled_at), "cancelled_by": m["user"].get(t.cancelled_by),
        "cancellation_reason": t.cancellation_reason,
    }


# ------------------------------------------------------------------ access
def _visible(user: User, scope: VendorScope):
    """Base condition every trip query must include: drivers see only their own trips."""
    if user.role == Role.DRIVER:
        return [Trip.driver_id == (user.driver_id if user.driver_id else -1)]
    cond = [] if scope.is_global else [Trip.vendor_id == scope.vendor_id]
    if (mine := operator_customer(user)) is not None:  # an Operator works for one customer only
        cond.append(Trip.customer_id == mine)
    return cond


def _get_visible(db: Session, user: User, scope: VendorScope, trip_id: int, lock: bool = False) -> Trip:
    q = select(Trip).where(Trip.id == trip_id, *_visible(user, scope))
    t = db.scalar(q.with_for_update() if lock else q)
    if t is None:
        raise HTTPException(404, "Not found")
    return t


def _local_bounds(d: date) -> tuple[datetime, datetime]:
    s = datetime.combine(d, time.min, tzinfo=tz())
    return s.astimezone(timezone.utc), datetime.combine(d, time.max, tzinfo=tz()).astimezone(timezone.utc)


def _history(db: Session, trip: Trip, to: TripStatus, by: User, from_: TripStatus | None = None, note: str | None = None):
    db.add(TripStatusHistory(trip_id=trip.id, from_status=from_.value if from_ else None, to_status=to.value,
                             changed_by=by.id, note=note))


# ------------------------------------------------------------------ list / detail
@router.get("")
def list_trips(
    q: str | None = None,
    view: Literal["all", "upcoming", "awaiting", "assigned", "accepted", "ongoing", "completed", "cancelled"] = "all",
    date_from: date | None = None, date_to: date | None = None,
    customer_id: int | None = None, site_id: int | None = None, employee_id: int | None = None,
    driver_id: int | None = None, vehicle_id: int | None = None, vendor_id: int | None = None,
    trip_type_id: int | None = None, shift_id: int | None = None, status: TripStatus | None = None,
    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("trip:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = _visible(user, scope)
    if scope.is_global and vendor_id and user.role != Role.DRIVER:
        cond.append(Trip.vendor_id == vendor_id)
    now = datetime.now(timezone.utc)
    asc = True
    if view == "upcoming":
        cond += [Trip.status.in_(OPEN), Trip.scheduled_end >= now]
    elif view == "awaiting":  # requests waiting for a Vendor Admin to assign a driver and vehicle
        cond.append(Trip.status == TripStatus.SCHEDULED)
    elif view == "assigned":
        cond.append(Trip.status == TripStatus.ASSIGNED)
    elif view == "accepted":
        cond.append(Trip.status == TripStatus.ACCEPTED)
    elif view == "ongoing":
        cond.append(Trip.status == TripStatus.STARTED)
    elif view == "completed":
        cond.append(Trip.status == TripStatus.COMPLETED); asc = False
    elif view == "cancelled":
        cond.append(Trip.status == TripStatus.CANCELLED); asc = False
    else:
        asc = False
    if status:
        cond.append(Trip.status == status)
    if date_from:
        cond.append(Trip.scheduled_start >= _local_bounds(date_from)[0])
    if date_to:
        cond.append(Trip.scheduled_start <= _local_bounds(date_to)[1])
    for col, val in ((Trip.customer_id, customer_id), (Trip.site_id, site_id), (Trip.driver_id, driver_id),
                     (Trip.vehicle_id, vehicle_id), (Trip.trip_type_id, trip_type_id), (Trip.shift_id, shift_id)):
        if val:
            cond.append(col == val)
    if employee_id:
        cond.append(exists().where(TripPassenger.trip_id == Trip.id, TripPassenger.employee_id == employee_id))
    if q:
        cond.append(Trip.code.ilike(f"%{q.strip()}%"))
    total = db.scalar(select(func.count()).select_from(Trip).where(*cond))
    order = (Trip.scheduled_start.asc(), Trip.id.asc()) if asc else (Trip.scheduled_start.desc(), Trip.id.desc())
    rows = db.scalars(select(Trip).where(*cond).order_by(*order).limit(limit).offset(offset)).all()
    m = _maps(db, rows)
    return {"total": total, "items": [_serialize(t, m, user) for t in rows]}


@router.get("/{trip_id}")
def get_trip(trip_id: int, user: User = Depends(require_permission("trip:read")),
             scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    t = _get_visible(db, user, scope, trip_id)
    m = _maps(db, [t])
    out = _serialize(t, m, user)
    hist = db.execute(
        select(TripStatusHistory, func.concat(User.first_name, " ", User.last_name))
        .join(User, User.id == TripStatusHistory.changed_by).where(TripStatusHistory.trip_id == t.id)
        .order_by(TripStatusHistory.changed_at, TripStatusHistory.id)).all()
    out["history"] = [{"from": h.from_status, "to": h.to_status, "by": name, "at": _iso(h.changed_at), "note": h.note} for h, name in hist]
    return out


@router.get("/{trip_id}/passengers")
def trip_passengers(trip_id: int, user: User = Depends(require_permission("trip:read")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    t = _get_visible(db, user, scope, trip_id)
    return _serialize(t, _maps(db, [t]), user)["passengers"]


# ------------------------------------------------------------------ create / edit
def _validate_refs(db: Session, scope: VendorScope, body: TripIn, customer: Customer, *, check_past: bool = True) -> list[Employee]:
    if customer.status != ActiveStatus.ACTIVE:
        raise field_error("customer_id", "Select an active customer")
    site = db.get(Site, body.site_id)
    if site is None or site.customer_id != customer.id:
        raise field_error("site_id", "Site does not belong to this customer")
    if site.status != ActiveStatus.ACTIVE:
        raise field_error("site_id", "Select an active site")
    check_lookup(db, body.trip_type_id, "trip_type", "trip_type_id", required=True)
    if body.shift_id is not None:
        sh = db.get(ShiftDefinition, body.shift_id)
        if sh is None or sh.customer_id != customer.id or sh.status != ActiveStatus.ACTIVE:
            raise field_error("shift_id", "Select an active shift of this customer")
    if check_past and body.scheduled_start < datetime.now(timezone.utc).replace(second=0, microsecond=0):
        raise field_error("scheduled_start", "Start time cannot be in the past")
    if body.scheduled_end <= body.scheduled_start:
        raise field_error("scheduled_end", "End time must be after the start time")
    emps = {e.id: e for e in db.scalars(select(Employee).where(Employee.id.in_(body.employee_ids)))}
    ordered = []
    for eid in body.employee_ids:
        e = emps.get(eid)
        if e is None or e.customer_id != customer.id:
            raise field_error("employee_ids", "Passengers must be employees of the selected customer")
        if e.status != ActiveStatus.ACTIVE:
            raise field_error("employee_ids", f"{e.first_name} {e.last_name} is inactive")
        ordered.append(e)
    return ordered


def _set_passengers(db: Session, trip: Trip, emps: list[Employee]) -> set[int]:
    """Makes the trip's passengers exactly `emps`, in order. Passengers who stay keep their row (and so their OTP and any
    drop-off result); removed ones are dropped; new ones are added with a fresh OTP if the trip is already assigned.
    Returns the employee ids that were newly added."""
    existing = {p.employee_id: p for p in db.scalars(select(TripPassenger).where(TripPassenger.trip_id == trip.id))}
    keep = {e.id for e in emps}
    for eid, p in existing.items():
        if eid not in keep:
            db.delete(p)
    added: set[int] = set()
    assigned = trip.driver_id is not None
    for i, e in enumerate(emps, 1):
        row = existing.get(e.id)
        if row is None:
            db.add(TripPassenger(trip_id=trip.id, employee_id=e.id, sequence=i, address=e.address, name=f"{e.first_name} {e.last_name}",
                                 mobile=e.mobile, gender=e.gender, otp_seed=otp.new_seed() if assigned else None))
            added.add(e.id)
        else:
            row.sequence = i
    db.flush()
    return added


def _issue_otps(db: Session, trip: Trip) -> None:
    """When a trip becomes final (driver + vehicle assigned), every passenger gets their own drop-off OTP."""
    for p in db.scalars(select(TripPassenger).where(TripPassenger.trip_id == trip.id)):
        if not p.otp_seed:
            p.otp_seed = otp.new_seed()
    db.flush()


def _commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:  # exclusion constraint = a concurrent request won the race
        db.rollback()
        if "ex_trip_" in str(exc.orig):
            who = "driver_id" if "driver" in str(exc.orig) else "vehicle_id"
            raise HTTPException(409, detail=[{"loc": ["body", who], "code": "conflict",
                                              "msg": "That resource was just booked by someone else. Pick another."}])
        raise


class PreviewIn(BaseModel):
    customer_id: int
    site_id: int
    trip_type_id: int
    scheduled_start: datetime
    pickup_address: str = ""
    drop_address: str = ""
    employee_ids: list[int] = Field(min_length=1)
    driver_id: int
    vehicle_id: int


@router.post("/sms-preview")
def sms_preview(body: PreviewIn, _: User = Depends(require_permission("trip:create")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    """Exactly what the driver and passengers will receive, before the trip is confirmed."""
    customer = db.get(Customer, body.customer_id)
    if customer is None:
        raise HTTPException(404, "Not found")
    scope.ensure(customer.vendor_id)
    site, driver, vehicle = db.get(Site, body.site_id), db.get(Driver, body.driver_id), db.get(Vehicle, body.vehicle_id)
    if not (site and driver and vehicle) or site.customer_id != customer.id \
            or driver.vendor_id != customer.vendor_id or vehicle.vendor_id != customer.vendor_id:
        raise HTTPException(404, "Not found")
    ttype = db.scalar(select(LookupValue.label).where(LookupValue.id == body.trip_type_id))
    emps = {e.id: e for e in db.scalars(select(Employee).where(Employee.id.in_(body.employee_ids),
                                                              Employee.customer_id == customer.id))}
    base = dict(code="TRP-(auto)", start=body.scheduled_start.astimezone(timezone.utc), customer=customer.name,
                site=site.name, vehicle=vehicle.vehicle_number, driver_name=f"{driver.first_name} {driver.last_name}",
                driver_phone=driver.contact_number)
    out = [{"recipient": f"{driver.first_name} {driver.last_name}", "type": "driver", "phone": notifications.sms.normalize_phone(driver.contact_number),
            "message": notifications.render("trip_created_driver", notifications.build_context(
                **base, pickup=body.pickup_address, drop=body.drop_address))}]
    for eid in body.employee_ids:
        e = emps.get(eid)
        if not e:
            continue
        pu = e.address if ttype == "Pickup" and e.address else body.pickup_address
        dr = e.address if ttype == "Drop" and e.address else body.drop_address
        out.append({"recipient": f"{e.first_name} {e.last_name}", "type": "employee", "phone": notifications.sms.normalize_phone(e.mobile),
                    "email": e.email,
                    # the real OTP does not exist yet, and when it does it is never shown here
                    "message": otp.mask(notifications.render("trip_created_employee", notifications.build_context(**base, pickup=pu, drop=dr)))})
    out[0]["email"] = notifications.driver_email(db, driver)
    sms_on, email_on = notifications.app_settings.channels(db, customer.vendor_id)
    return {"messages": out, "channels": {"sms": sms_on, "email": email_on}}


@router.post("", status_code=201)
def create_trip(body: TripIn, background: BackgroundTasks, actor: User = Depends(require_permission("trip:create")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    """Two ways in:
      * REQUEST – no driver/vehicle (what an Operator sends). Status "scheduled" = awaiting assignment; nothing is
        reserved and nobody is notified until a Vendor Admin assigns.
      * DIRECT – driver + vehicle given. Only someone who may assign (Vendor Admin / Super Admin) can do this; the trip is
        created already assigned and the driver and passengers are notified."""
    mine = require_operator_customer(actor)
    if mine is not None:  # an Operator always requests for their own customer, whatever was sent
        body = body.model_copy(update={"customer_id": mine})
    if body.customer_id is None:
        raise field_error("customer_id", "Customer is required")
    direct = body.driver_id is not None or body.vehicle_id is not None
    if direct:
        if not has_permission(actor.role, "trip:assign"):
            raise HTTPException(403, "Only a Vendor Admin can assign a driver and vehicle. Send the request without them.")
        if body.driver_id is None:
            raise field_error("driver_id", "Driver is required")
        if body.vehicle_id is None:
            raise field_error("vehicle_id", "Vehicle is required")
    customer = db.get(Customer, body.customer_id)
    if customer is None:
        raise HTTPException(404, "Not found")
    scope.ensure(customer.vendor_id)
    emps = _validate_refs(db, scope, body, customer)
    escort, needed = avail.required_capacity(len(emps), any(e.gender == "female" for e in emps))
    if direct:
        avail.assert_assignable(db, vendor_id=customer.vendor_id, driver_id=body.driver_id, vehicle_id=body.vehicle_id,
                                start=body.scheduled_start, end=body.scheduled_end, needed_capacity=needed)
    t = Trip(
        vendor_id=customer.vendor_id, customer_id=customer.id, site_id=body.site_id, trip_type_id=body.trip_type_id,
        shift_id=body.shift_id, scheduled_start=body.scheduled_start, scheduled_end=body.scheduled_end,
        block_end=avail.block_end(body.scheduled_end), route_name=body.route_name,
        special_instructions=body.special_instructions, pickup_address=body.pickup_address,
        pickup_latitude=body.pickup_latitude, pickup_longitude=body.pickup_longitude, drop_address=body.drop_address,
        drop_latitude=body.drop_latitude, drop_longitude=body.drop_longitude, passenger_count=len(emps),
        escort_required=escort, required_capacity=needed, driver_id=body.driver_id, vehicle_id=body.vehicle_id,
        status=TripStatus.ASSIGNED if direct else TripStatus.SCHEDULED, created_by=actor.id,
    )
    db.add(t)
    db.flush()
    t.code = f"TRP-{t.id:06d}"
    _set_passengers(db, t, emps)  # a trip created already assigned gives every passenger an OTP right here
    sms_ids = notifications.EMPTY
    if direct:
        db.add(TripAssignment(trip_id=t.id, driver_id=t.driver_id, vehicle_id=t.vehicle_id, assigned_by=actor.id))
        _history(db, t, TripStatus.ASSIGNED, actor, note="Created and assigned")
        audit.record(db, "trip.created", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                     detail={"code": t.code, "driver_id": t.driver_id, "vehicle_id": t.vehicle_id, "passengers": len(emps)})
        sms_ids = notifications.queue_trip_created(db, t)  # logged 'pending' in the same transaction
    else:
        _history(db, t, TripStatus.SCHEDULED, actor, note="Requested – awaiting assignment")
        audit.record(db, "trip.requested", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                     detail={"code": t.code, "passengers": len(emps)})
    _commit(db)
    background.add_task(notifications.deliver, sms_ids)  # sent after commit: provider trouble never affects the trip
    return _serialize(t, _maps(db, [t]), actor)


def _merge(a: tuple[list[int], list[int]], b: tuple[list[int], list[int]]) -> tuple[list[int], list[int]]:
    return (a[0] + b[0], a[1] + b[1])


def _may_change(actor: User, t: Trip) -> None:
    """Operators manage only requests still awaiting assignment; once a Vendor Admin has assigned, it's theirs."""
    if not has_permission(actor.role, "trip:assign") and t.status != TripStatus.SCHEDULED:
        raise HTTPException(403, "A Vendor Admin has already assigned this trip. Ask them to make the change.")


_OPERATIONAL = ("site_id", "trip_type_id", "shift_id", "scheduled_start", "scheduled_end", "route_name", "pickup_address",
                "pickup_latitude", "pickup_longitude", "drop_address", "drop_latitude", "drop_longitude")


def _reassign(db: Session, trip: Trip, actor: User, driver_id: int, vehicle_id: int) -> tuple[bool, bool]:
    """Moves the trip to another driver/vehicle, keeping the assignment history. Returns (driver_changed, vehicle_changed)."""
    dc, vc = driver_id != trip.driver_id, vehicle_id != trip.vehicle_id
    if dc or vc:
        for a in db.scalars(select(TripAssignment).where(TripAssignment.trip_id == trip.id, TripAssignment.released_at.is_(None))):
            a.released_at = datetime.now(timezone.utc)
        trip.driver_id, trip.vehicle_id = driver_id, vehicle_id
        db.add(TripAssignment(trip_id=trip.id, driver_id=driver_id, vehicle_id=vehicle_id, assigned_by=actor.id))
        if dc and trip.status == TripStatus.ACCEPTED:  # the new driver has not accepted yet
            _history(db, trip, TripStatus.ASSIGNED, actor, TripStatus.ACCEPTED, "Driver changed")
            trip.status, trip.accepted_at = TripStatus.ASSIGNED, None
    return dc, vc


@router.put("/{trip_id}")
def edit_trip(trip_id: int, body: TripIn, background: BackgroundTasks, actor: User = Depends(require_permission("trip:edit")),
              scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    t = _get_visible(db, actor, scope, trip_id, lock=True)
    if t.status in (TripStatus.COMPLETED, TripStatus.CANCELLED):
        raise HTTPException(409, f"A {t.status.value} trip can no longer be edited")
    _may_change(actor, t)
    if body.customer_id is not None and body.customer_id != t.customer_id:
        raise field_error("customer_id", "The customer of a trip cannot be changed")
    customer = db.get(Customer, t.customer_id)
    # Only a changed start time must be in the future — a trip already under way can still have other details edited.
    emps = _validate_refs(db, scope, body, customer, check_past=body.scheduled_start != t.scheduled_start)

    if t.status == TripStatus.SCHEDULED:  # a request: nothing is reserved, so there is nothing to re-check
        if body.driver_id is not None or body.vehicle_id is not None:
            raise field_error("driver_id", "Use 'Assign' to choose a driver and vehicle for a request")
        changed = [f for f in _OPERATIONAL if getattr(body, f) != getattr(t, f)]
        if [p.employee_id for p in _passengers(db, [t.id]).get(t.id, [])] != body.employee_ids:
            changed.append("passengers")
            _set_passengers(db, t, emps)
        escort, needed = avail.required_capacity(len(emps), any(e.gender == "female" for e in emps))
        for f in _OPERATIONAL:
            setattr(t, f, getattr(body, f))
        t.block_end = avail.block_end(t.scheduled_end)
        t.passenger_count, t.escort_required, t.required_capacity = len(emps), escort, needed
        if t.special_instructions != body.special_instructions:
            t.special_instructions = body.special_instructions
            changed.append("special_instructions")
        audit.record(db, "trip.updated", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                     detail={"code": t.code, "changed": changed, "awaiting_assignment": True})
        db.commit()
        return _serialize(t, _maps(db, [t]), actor)

    new_driver, new_vehicle = body.driver_id or t.driver_id, body.vehicle_id or t.vehicle_id
    old_pax = [p.employee_id for p in _passengers(db, [t.id]).get(t.id, [])]

    changed = [f for f in _OPERATIONAL if getattr(body, f) != getattr(t, f)]
    if old_pax != body.employee_ids:
        changed.append("passengers")
    if new_driver != t.driver_id:
        changed.append("driver")
    if new_vehicle != t.vehicle_id:
        changed.append("vehicle")
    if t.status == TripStatus.STARTED and changed:
        raise HTTPException(409, "A started trip can only have its instructions edited")

    sms_ids = notifications.EMPTY
    old_driver = t.driver_id
    if changed:
        escort, needed = avail.required_capacity(len(emps), any(e.gender == "female" for e in emps))
        avail.assert_assignable(db, vendor_id=t.vendor_id, driver_id=new_driver, vehicle_id=new_vehicle,
                                start=body.scheduled_start, end=body.scheduled_end, needed_capacity=needed,
                                exclude_trip_id=t.id)
        for f in _OPERATIONAL:
            setattr(t, f, getattr(body, f))
        t.block_end = avail.block_end(t.scheduled_end)
        t.passenger_count, t.escort_required, t.required_capacity = len(emps), escort, needed
        added: set[int] = _set_passengers(db, t, emps) if "passengers" in changed else set()
        dc, vc = _reassign(db, t, actor, new_driver, new_vehicle)
        if dc or vc:
            sms_ids = notifications.queue_trip_reassigned(db, t, old_driver, dc)  # only if the setting is on
        if added:  # someone joined an already-assigned trip: they get the "your trip is booked" message with their own OTP
            sms_ids = _merge(sms_ids, notifications.queue_trip_created(db, t, only_employee_ids=added))
    if t.special_instructions != body.special_instructions:
        t.special_instructions = body.special_instructions
        changed.append("special_instructions")
    audit.record(db, "trip.updated", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                 detail={"code": t.code, "changed": changed})
    _commit(db)
    background.add_task(notifications.deliver, sms_ids)
    return _serialize(t, _maps(db, [t]), actor)


@router.post("/{trip_id}/assign")
def assign_trip(trip_id: int, body: AssignIn, background: BackgroundTasks, actor: User = Depends(require_permission("trip:assign")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    t = _get_visible(db, actor, scope, trip_id, lock=True)
    if t.status not in OPEN:
        raise HTTPException(409, f"A {t.status.value} trip cannot be assigned")

    if t.status == TripStatus.SCHEDULED:
        # First assignment: a request becomes a real trip. Needs BOTH a driver and a vehicle; then the driver and
        # every passenger are notified (the "final trip" notification).
        if body.driver_id is None:
            raise field_error("driver_id", "Choose a driver")
        if body.vehicle_id is None:
            raise field_error("vehicle_id", "Choose a vehicle")
        avail.assert_assignable(db, vendor_id=t.vendor_id, driver_id=body.driver_id, vehicle_id=body.vehicle_id,
                                start=t.scheduled_start, end=t.scheduled_end, needed_capacity=t.required_capacity,
                                exclude_trip_id=t.id)
        t.driver_id, t.vehicle_id, t.status = body.driver_id, body.vehicle_id, TripStatus.ASSIGNED
        db.add(TripAssignment(trip_id=t.id, driver_id=t.driver_id, vehicle_id=t.vehicle_id, assigned_by=actor.id))
        _history(db, t, TripStatus.ASSIGNED, actor, TripStatus.SCHEDULED, "Driver and vehicle assigned")
        audit.record(db, "trip.assigned", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                     detail={"code": t.code, "driver_id": t.driver_id, "vehicle_id": t.vehicle_id})
        _issue_otps(db, t)  # each employee now gets their own drop-off OTP (sent in their notification below)
        sms_ids = notifications.queue_trip_created(db, t)
        _commit(db)
        background.add_task(notifications.deliver, sms_ids)
        return _serialize(t, _maps(db, [t]), actor)

    if body.driver_id is None and body.vehicle_id is None:
        raise field_error("driver_id", "Choose a driver and/or a vehicle")
    driver_id, vehicle_id = body.driver_id or t.driver_id, body.vehicle_id or t.vehicle_id
    avail.assert_assignable(db, vendor_id=t.vendor_id, driver_id=driver_id, vehicle_id=vehicle_id, start=t.scheduled_start,
                            end=t.scheduled_end, needed_capacity=t.required_capacity, exclude_trip_id=t.id)
    old_driver = t.driver_id
    dc, vc = _reassign(db, t, actor, driver_id, vehicle_id)
    audit.record(db, "trip.reassigned", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                 detail={"code": t.code, "driver_id": driver_id, "vehicle_id": vehicle_id})
    sms_ids = notifications.queue_trip_reassigned(db, t, old_driver, dc) if (dc or vc) else notifications.EMPTY
    _commit(db)
    background.add_task(notifications.deliver, sms_ids)
    return _serialize(t, _maps(db, [t]), actor)


@router.post("/{trip_id}/cancel")
def cancel_trip(trip_id: int, body: CancelIn, background: BackgroundTasks, actor: User = Depends(require_permission("trip:cancel")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    t = _get_visible(db, actor, scope, trip_id, lock=True)
    if t.status not in OPEN:
        raise HTTPException(409, f"A {t.status.value} trip cannot be cancelled")
    _may_change(actor, t)  # Operators: only requests still awaiting assignment
    prev = t.status
    t.status, t.cancelled_at, t.cancelled_by, t.cancellation_reason = TripStatus.CANCELLED, datetime.now(timezone.utc), actor.id, body.reason.strip()
    for a in db.scalars(select(TripAssignment).where(TripAssignment.trip_id == t.id, TripAssignment.released_at.is_(None))):
        a.released_at = t.cancelled_at  # resources are free again (cancelled trips never block availability)
    _history(db, t, TripStatus.CANCELLED, actor, prev, body.reason.strip())
    audit.record(db, "trip.cancelled", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                 detail={"code": t.code, "reason": t.cancellation_reason})
    sms_ids = notifications.queue_trip_cancelled(db, t)
    _commit(db)
    background.add_task(notifications.deliver, sms_ids)
    return _serialize(t, _maps(db, [t]), actor)


# ------------------------------------------------------------------ driver workflow
_TRANSITIONS = {
    "accepted": ((TripStatus.ASSIGNED,), TripStatus.ACCEPTED, "accepted_at"),  # a request has no driver yet
    "started": ((TripStatus.ACCEPTED,), TripStatus.STARTED, "started_at"),
    "completed": ((TripStatus.STARTED,), TripStatus.COMPLETED, "completed_at"),
}


@router.post("/{trip_id}/status")
def driver_update_status(trip_id: int, body: DriverStatusIn, actor: User = Depends(require_permission("trip:driver_status")),
                         scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    t = _get_visible(db, actor, scope, trip_id, lock=True)  # row lock: double-taps/retries serialise, the 2nd gets 409
    allowed_from, target, stamp = _TRANSITIONS[body.status]
    if t.status not in allowed_from:
        raise HTTPException(409, f"This trip is already {t.status.value}; it cannot be marked {body.status}")
    note = None
    if body.status == "completed":
        # The trip can only end once every employee has been dropped: their OTP verified, or marked "not dropped".
        pax = list(db.scalars(select(TripPassenger).where(TripPassenger.trip_id == t.id).order_by(TripPassenger.sequence)))
        waiting = [p.name for p in pax if drop_status(p) in ("pending", "none")]
        if waiting:
            raise HTTPException(409, detail=[{"loc": ["body", "status"], "code": "otp_pending",
                                              "msg": f"{len(waiting)} employee{'s' if len(waiting) > 1 else ''} still to be dropped: "
                                                     f"{', '.join(waiting)}. Verify their OTP at the drop point, or mark them as not dropped."}])
        skipped = [p for p in pax if drop_status(p) == "not_dropped"]
        if skipped:
            note = f"{len(skipped)} employee(s) not dropped: " + "; ".join(f"{p.name} ({p.not_dropped_reason})" for p in skipped)
    prev = t.status
    t.status = target
    setattr(t, stamp, datetime.now(timezone.utc))
    _history(db, t, target, actor, prev, note)
    audit.record(db, f"trip.{body.status}", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                 detail={"code": t.code})
    _commit(db)
    return _serialize(t, _maps(db, [t]), actor)


# ------------------------------------------------------------------ live map
class LocationIn(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


def _stop(kind: str, label: str, lat: float | None, lng: float | None, **extra) -> dict | None:
    return None if lat is None or lng is None else {"kind": kind, "label": label, "latitude": lat, "longitude": lng, **extra}


@router.get("/{trip_id}/route")
def trip_route(trip_id: int, user: User = Depends(require_permission("trip:read")),
               scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    """Ordered stops for the map: pickup, every employee's stop in sequence, drop - plus the driver's last position."""
    t = _get_visible(db, user, scope, trip_id)
    site = db.get(Site, t.site_id)
    ttype = db.scalar(select(LookupValue.label).where(LookupValue.id == t.trip_type_id))
    # Without explicit coordinates the office is the other end of the route (drop on Pickup trips, start on Drop trips).
    pu = (t.pickup_latitude, t.pickup_longitude)
    dr = (t.drop_latitude, t.drop_longitude)
    if None in pu and ttype == "Drop" and site:
        pu = (site.latitude, site.longitude)
    if None in dr and ttype == "Pickup" and site:
        dr = (site.latitude, site.longitude)
    # Drop trip: leaves the pickup point and ends at the last employee. Pickup trip: collects the employees and ends at the drop point.
    employees = []
    for p in db.scalars(select(TripPassenger).where(TripPassenger.trip_id == t.id).order_by(TripPassenger.sequence)):
        e = db.get(Employee, p.employee_id)
        if e and (e.latitude is None or e.longitude is None) and (g := geocode.geocode(e.address or p.address, site.city if site else None)):
            e.latitude, e.longitude = g
            db.commit()
        employees.append(_stop("employee", p.name, e.latitude if e else None, e.longitude if e else None,
                               address=p.address, sequence=p.sequence, status=drop_status(p)))
    # The customer's office: the site's coordinates, else the customer's own.
    cust = db.get(Customer, t.customer_id)
    office = None
    for src in (site, cust):
        if src is not None and src.latitude is not None and src.longitude is not None:
            office = {"name": cust.name if cust else (site.name if site else ""), "site": site.name if site else None,
                      "address": (site.address if site else None) or (cust.address if cust else None),
                      "latitude": src.latitude, "longitude": src.longitude}
            break
    # Only without an office location: the trip form only collects addresses, so look the missing end up once and keep the result on the trip.
    need_pu = office is None and ttype != "Pickup" and None in pu
    need_dr = office is None and ttype != "Drop" and None in dr
    if need_pu and (g := geocode.geocode(t.pickup_address, site.city if site else None)):
        t.pickup_latitude, t.pickup_longitude = pu = g
    if need_dr and (g := geocode.geocode(t.drop_address, site.city if site else None)):
        t.drop_latitude, t.drop_longitude = dr = g
    if (need_pu or need_dr) and db.is_modified(t):
        db.commit()
    # The route always runs to/from the customer's office: Drop trips leave it, Pickup trips end at it. The trip's own
    # pickup/drop address is only used when the office has no coordinates.
    o = _stop("office", office["name"], office["latitude"], office["longitude"], address=office["address"], status=None) if office else None
    start = [o or _stop("pickup", t.pickup_address, *pu, status=None)] if ttype != "Pickup" else []
    end = [o or _stop("drop", t.drop_address, *dr, status=None)] if ttype != "Drop" else []
    stops = start + employees + end
    all_stops = [s for s in stops if s]
    live = None
    if t.status == TripStatus.STARTED and t.last_latitude is not None:
        live = {"latitude": t.last_latitude, "longitude": t.last_longitude, "at": _iso(t.last_location_at)}
    veh = db.get(Vehicle, t.vehicle_id) if t.vehicle_id else None
    return {"trip_id": t.id, "code": t.code, "status": t.status.value, "trip_type": ttype, "stops": all_stops,
            "customer_location": office, "vehicle_code": veh.vehicle_code if veh else None, "vehicle_number": veh.vehicle_number if veh else None,
            "missing": len(stops) - len(all_stops), "live": live}


@router.post("/{trip_id}/location", status_code=204)
def report_location(trip_id: int, body: LocationIn, actor: User = Depends(require_permission("trip:driver_status")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    """The driver's device reports its position while the trip is in progress."""
    t = _get_visible(db, actor, scope, trip_id, lock=True)
    if t.status != TripStatus.STARTED:
        raise HTTPException(409, "Location is only shared while the trip is in progress")
    t.last_latitude, t.last_longitude, t.last_location_at = body.latitude, body.longitude, datetime.now(timezone.utc)
    _commit(db)


class OtpIn(BaseModel):
    otp: str = Field(min_length=1, max_length=12)


class NotDroppedIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


def _passenger_for_drop(db: Session, actor: User, scope: VendorScope, trip_id: int, employee_id: int) -> tuple[Trip, TripPassenger]:
    t = _get_visible(db, actor, scope, trip_id, lock=True)  # a driver can only reach their own trips; locks out concurrent taps
    if t.status != TripStatus.STARTED:
        raise HTTPException(409, "Employees can only be dropped while the trip is in progress")
    p = db.scalar(select(TripPassenger).where(TripPassenger.trip_id == t.id, TripPassenger.employee_id == employee_id).with_for_update())
    if p is None:
        raise HTTPException(404, "Not found")
    state = drop_status(p)
    if state == "verified":
        raise HTTPException(409, f"{p.name} has already been dropped")
    if state == "not_dropped":
        raise HTTPException(409, f"{p.name} was already marked as not dropped")
    if state == "none":
        raise HTTPException(409, "This employee has no OTP. Ask the Vendor Admin to re-assign the trip.")
    return t, p


@router.post("/{trip_id}/passengers/{employee_id}/verify-otp")
def verify_passenger_otp(trip_id: int, employee_id: int, body: OtpIn, actor: User = Depends(require_permission("trip:driver_status")),
                         scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    """The driver types the OTP the employee reads out at the drop point. Wrong tries are counted and limited."""
    t, p = _passenger_for_drop(db, actor, scope, trip_id, employee_id)
    limit = get_settings().otp_max_attempts
    if p.otp_attempts >= limit:
        raise HTTPException(423, detail=[{"loc": ["body", "otp"], "code": "otp_locked",
                                          "msg": f"Too many wrong OTPs for {p.name}. If they cannot share it, mark them as not dropped."}])
    if otp.matches(p.otp_seed, t.id, p.employee_id, body.otp):
        p.otp_verified_at, p.otp_verified_by = datetime.now(timezone.utc), actor.id
        audit.record(db, "trip.otp_verified", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                     detail={"code": t.code, "employee_id": p.employee_id})
        _commit(db)
        return _serialize(t, _maps(db, [t]), actor)
    p.otp_attempts += 1
    left = limit - p.otp_attempts
    audit.record(db, "trip.otp_failed" if left > 0 else "trip.otp_locked", actor, entity_type="trip", entity_id=t.id,
                 vendor_id=t.vendor_id, detail={"code": t.code, "employee_id": p.employee_id, "attempts": p.otp_attempts})  # never the code
    _commit(db)  # the failed try must be saved even though we are about to refuse it
    msg = (f"That OTP is not correct. {left} {'try' if left == 1 else 'tries'} left." if left > 0
           else f"Too many wrong OTPs for {p.name}. If they cannot share it, mark them as not dropped.")
    raise HTTPException(422 if left > 0 else 423, detail=[{"loc": ["body", "otp"], "code": "otp_wrong" if left > 0 else "otp_locked", "msg": msg}])


@router.post("/{trip_id}/passengers/{employee_id}/not-dropped")
def mark_not_dropped(trip_id: int, employee_id: int, body: NotDroppedIn, actor: User = Depends(require_permission("trip:driver_status")),
                     scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    """The driver's way out when an employee doesn't show up or can't share the OTP. Needs a reason; it is flagged to admins."""
    t, p = _passenger_for_drop(db, actor, scope, trip_id, employee_id)
    p.not_dropped_at, p.not_dropped_by, p.not_dropped_reason = datetime.now(timezone.utc), actor.id, body.reason.strip()
    audit.record(db, "trip.passenger_not_dropped", actor, entity_type="trip", entity_id=t.id, vendor_id=t.vendor_id,
                 detail={"code": t.code, "employee_id": p.employee_id, "reason": p.not_dropped_reason})
    _commit(db)
    return _serialize(t, _maps(db, [t]), actor)
