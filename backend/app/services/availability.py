"""The ONE place that knows the scheduling rules (spec 2.6, 2.7, 23).

Rule: a trip occupies [scheduled_start, scheduled_end + BUFFER). Two non-cancelled trips of the same
driver (or vehicle) may not overlap, i.e. there must be at least BUFFER minutes between one trip's end
and the next trip's start. Example: a trip ending 10:00 blocks the resource until 10:30, so the next
trip can start at 10:30 but not 10:29. Cancelled trips never block anything.

Vehicle capacity must be >= passengers + escort seat (1 if any passenger is female, else 0).
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import to_local
from app.models import ActiveStatus, Driver, Trip, TripStatus, Vehicle


def buffer() -> timedelta:
    return timedelta(minutes=get_settings().availability_buffer_minutes)


def block_end(scheduled_end: datetime) -> datetime:
    return scheduled_end + buffer()


def required_capacity(passenger_count: int, has_female: bool) -> tuple[bool, int]:
    """Returns (escort_required, required_capacity)."""
    escort = 1 if has_female else 0
    return bool(escort), passenger_count + escort


def _overlapping(resource_col, ids, start: datetime, end: datetime, exclude_trip_id: int | None):
    q = select(Trip).where(
        resource_col.in_(ids),
        Trip.status != TripStatus.CANCELLED,
        Trip.scheduled_start < block_end(end),
        Trip.block_end > start,
    )
    if exclude_trip_id:
        q = q.where(Trip.id != exclude_trip_id)
    return q


@dataclass
class Availability:
    resource: object
    reasons: list[dict] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return not self.reasons


def _conflict_reason(code: str, who: str, t: Trip) -> dict:
    s, e = to_local(t.scheduled_start), to_local(t.scheduled_end)
    return {"code": code, "message": f"{who} is already booked on {t.code} ({s:%d %b %H:%M}–{e:%H:%M}) and needs a {get_settings().availability_buffer_minutes}-minute gap",
            "trip_id": t.id, "trip_code": t.code}


def driver_availability(db: Session, vendor_id: int, start: datetime, end: datetime,
                        exclude_trip_id: int | None = None) -> list[Availability]:
    drivers = db.scalars(select(Driver).where(Driver.vendor_id == vendor_id).order_by(Driver.first_name, Driver.id)).all()
    clashes: dict[int, Trip] = {}
    if drivers:
        for t in db.scalars(_overlapping(Trip.driver_id, [d.id for d in drivers], start, end, exclude_trip_id)):
            clashes.setdefault(t.driver_id, t)
    out = []
    for d in drivers:
        a = Availability(d)
        if d.status != ActiveStatus.ACTIVE:
            a.reasons.append({"code": "driver_inactive", "message": "Driver is inactive"})
        if d.id in clashes:
            a.reasons.append(_conflict_reason("driver_conflict", "Driver", clashes[d.id]))
        out.append(a)
    return out


def vehicle_availability(db: Session, vendor_id: int, start: datetime, end: datetime, needed_capacity: int,
                         exclude_trip_id: int | None = None) -> list[Availability]:
    vehicles = db.scalars(select(Vehicle).where(Vehicle.vendor_id == vendor_id).order_by(Vehicle.vehicle_number)).all()
    clashes: dict[int, Trip] = {}
    if vehicles:
        for t in db.scalars(_overlapping(Trip.vehicle_id, [v.id for v in vehicles], start, end, exclude_trip_id)):
            clashes.setdefault(t.vehicle_id, t)
    out = []
    for v in vehicles:
        a = Availability(v)
        if v.status != ActiveStatus.ACTIVE:
            a.reasons.append({"code": "vehicle_inactive", "message": "Vehicle is inactive"})
        if v.capacity < needed_capacity:
            a.reasons.append({"code": "capacity_too_low",
                              "message": f"Capacity {v.capacity} is below the {needed_capacity} seats required"})
        if v.id in clashes:
            a.reasons.append(_conflict_reason("vehicle_conflict", "Vehicle", clashes[v.id]))
        out.append(a)
    return out


def _problem(field_name: str, code: str, message: str, status: int = 409) -> HTTPException:
    return HTTPException(status, detail=[{"loc": ["body", field_name], "msg": message, "code": code}])


def assert_assignable(db: Session, *, vendor_id: int, driver_id: int, vehicle_id: int, start: datetime, end: datetime,
                      needed_capacity: int, exclude_trip_id: int | None = None) -> tuple[Driver, Vehicle]:
    """Final server-side gate used by trip create / edit / reassign.

    Locks the driver and vehicle rows first so two operators assigning the same resource at once are
    serialised (the second sees the first's trip). The DB exclusion constraints are the last backstop.
    """
    driver = db.scalar(select(Driver).where(Driver.id == driver_id).with_for_update())
    vehicle = db.scalar(select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update())
    if driver is None or driver.vendor_id != vendor_id:
        raise _problem("driver_id", "driver_invalid", "Select a driver of this vendor", 422)
    if vehicle is None or vehicle.vendor_id != vendor_id:
        raise _problem("vehicle_id", "vehicle_invalid", "Select a vehicle of this vendor", 422)
    if driver.status != ActiveStatus.ACTIVE:
        raise _problem("driver_id", "driver_inactive", "This driver is inactive")
    if vehicle.status != ActiveStatus.ACTIVE:
        raise _problem("vehicle_id", "vehicle_inactive", "This vehicle is inactive")
    if vehicle.capacity < needed_capacity:
        raise _problem("vehicle_id", "capacity_too_low",
                       f"Vehicle seats {vehicle.capacity} but {needed_capacity} are required (including any escort seat)")
    d_clash = db.scalar(_overlapping(Trip.driver_id, [driver_id], start, end, exclude_trip_id).limit(1))
    if d_clash:
        raise _problem("driver_id", "driver_conflict", _conflict_reason("", "Driver", d_clash)["message"])
    v_clash = db.scalar(_overlapping(Trip.vehicle_id, [vehicle_id], start, end, exclude_trip_id).limit(1))
    if v_clash:
        raise _problem("vehicle_id", "vehicle_conflict", _conflict_reason("", "Vehicle", v_clash)["message"])
    return driver, vehicle
