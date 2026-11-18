"""Read-only aggregations behind the dashboard and the reports. Everything here is vendor-scoped through
`Filters.vendor_id` (set by the route from the caller's scope), never from raw request input."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.timeutil import local_date, tz
from app.models import (
    ActiveStatus, Customer, Driver, ShiftDefinition, SmsLog, Trip, TripPassenger, TripStatus, Vehicle, Vendor,
)

NOT_CANCELLED = Trip.status != TripStatus.CANCELLED
OPEN = (TripStatus.SCHEDULED, TripStatus.ASSIGNED, TripStatus.ACCEPTED)
RANGES = ("today", "tomorrow", "this_week", "this_month", "custom")


@dataclass
class Filters:
    start: datetime
    end: datetime
    label: str
    vendor_id: int | None = None
    customer_id: int | None = None
    site_id: int | None = None
    status: TripStatus | None = None
    trip_type_id: int | None = None
    shift_id: int | None = None


def _bounds(first: date, last: date) -> tuple[datetime, datetime]:
    """[first 00:00, last+1 00:00) in the business timezone, as UTC instants."""
    z = tz()
    return (datetime.combine(first, time.min, tzinfo=z).astimezone(timezone.utc),
            datetime.combine(last + timedelta(days=1), time.min, tzinfo=z).astimezone(timezone.utc))


def resolve_range(preset: str, date_from: date | None, date_to: date | None) -> tuple[datetime, datetime, str]:
    today = local_date(datetime.now(timezone.utc))
    if preset == "today":
        first = last = today
    elif preset == "tomorrow":
        first = last = today + timedelta(days=1)
    elif preset == "this_week":  # weeks run Monday–Sunday
        first = today - timedelta(days=today.weekday())
        last = first + timedelta(days=6)
    elif preset == "this_month":
        first = today.replace(day=1)
        last = (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    elif preset == "custom":
        if not date_from or not date_to:
            raise HTTPException(422, detail=[{"loc": ["query", "date_from"], "msg": "Choose a start and end date"}])
        if date_to < date_from:
            raise HTTPException(422, detail=[{"loc": ["query", "date_to"], "msg": "End date must not be before the start date"}])
        if (date_to - date_from).days > 366:
            raise HTTPException(422, detail=[{"loc": ["query", "date_to"], "msg": "Choose a range of at most one year"}])
        first, last = date_from, date_to
    else:
        raise HTTPException(422, detail=[{"loc": ["query", "range"], "msg": "Unknown range"}])
    s, e = _bounds(first, last)
    return s, e, f"{first:%d %b %Y}" if first == last else f"{first:%d %b %Y} – {last:%d %b %Y}"


def resolve_dates(preset: str, date_from: date | None, date_to: date | None) -> tuple[date, date, str]:
    """Whole local days [first, last] for date-based data (expenses). Weeks run Monday–Sunday."""
    today = local_date(datetime.now(timezone.utc))
    month_start = today.replace(day=1)
    if preset == "today":
        first = last = today
    elif preset == "this_week":
        first = today - timedelta(days=today.weekday())
        last = first + timedelta(days=6)
    elif preset == "this_month":
        first, last = month_start, (month_start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    elif preset == "last_month":
        last = month_start - timedelta(days=1)
        first = last.replace(day=1)
    elif preset == "this_year":
        first, last = today.replace(month=1, day=1), today.replace(month=12, day=31)
    elif preset == "custom":
        if not date_from or not date_to:
            raise HTTPException(422, detail=[{"loc": ["query", "date_from"], "msg": "Choose a start and end date"}])
        if date_to < date_from:
            raise HTTPException(422, detail=[{"loc": ["query", "date_to"], "msg": "End date must not be before the start date"}])
        if (date_to - date_from).days > 731:
            raise HTTPException(422, detail=[{"loc": ["query", "date_to"], "msg": "Choose a range of at most two years"}])
        first, last = date_from, date_to
    else:
        raise HTTPException(422, detail=[{"loc": ["query", "range"], "msg": "Unknown range"}])
    return first, last, f"{first:%d %b %Y}" if first == last else f"{first:%d %b %Y} – {last:%d %b %Y}"


def trip_cond(f: Filters) -> list:
    c = [Trip.scheduled_start >= f.start, Trip.scheduled_start < f.end]
    for col, val in ((Trip.vendor_id, f.vendor_id), (Trip.customer_id, f.customer_id), (Trip.site_id, f.site_id),
                     (Trip.status, f.status), (Trip.trip_type_id, f.trip_type_id), (Trip.shift_id, f.shift_id)):
        if val is not None:
            c.append(col == val)
    return c


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pct(a, b) -> float:
    return round(100.0 * (a or 0) / b, 1) if b else 0.0


# ------------------------------------------------------------------ summary cards
def summary(db: Session, f: Filters) -> dict:
    cond, now = trip_cond(f), _now()
    n = lambda *st: func.count().filter(Trip.status.in_(st))  # noqa: E731
    live = Trip.status != TripStatus.CANCELLED
    r = db.execute(
        select(
            func.count(), n(*OPEN), n(TripStatus.ASSIGNED), n(TripStatus.SCHEDULED), n(TripStatus.ACCEPTED), n(TripStatus.STARTED),
            n(TripStatus.COMPLETED), n(TripStatus.CANCELLED),
            func.coalesce(func.sum(Trip.passenger_count).filter(live), 0),
            # seat use only counts trips that already have a vehicle (requests awaiting assignment have none)
            func.coalesce(func.sum(Trip.required_capacity).filter(live, Trip.vehicle_id.is_not(None)), 0),
            func.coalesce(func.sum(Vehicle.capacity).filter(live), 0),
            func.count().filter(live, Trip.escort_required),
            func.count().filter(Trip.status.in_(OPEN), Trip.scheduled_end >= now),
        ).select_from(Trip).outerjoin(Vehicle, Vehicle.id == Trip.vehicle_id).where(*cond)
    ).one()
    total, _open, assigned, scheduled, accepted, started, completed, cancelled, pax, need, seats, escorts, upcoming = r

    sms = dict(db.execute(
        select(SmsLog.status, func.count()).where(SmsLog.trip_id.in_(select(Trip.id).where(*cond))).group_by(SmsLog.status)).all())

    def resources(model, col):
        vendor = [] if f.vendor_id is None else [model.vendor_id == f.vendor_id]
        active = db.scalar(select(func.count()).select_from(model).where(model.status == ActiveStatus.ACTIVE, *vendor)) or 0
        # "available" uses the booking engine's own rule (booked time + trailing buffer), so the card agrees with
        # what the trip form will offer right now; "in use" = on a trip at this moment.
        blocked = select(col).where(NOT_CANCELLED, Trip.scheduled_start <= now, Trip.block_end > now)
        in_use = select(col).where(NOT_CANCELLED, Trip.scheduled_start <= now, Trip.scheduled_end > now)
        free = db.scalar(select(func.count()).select_from(model).where(model.status == ActiveStatus.ACTIVE, model.id.not_in(blocked), *vendor)) or 0
        busy = db.scalar(select(func.count()).select_from(model).where(model.status == ActiveStatus.ACTIVE, model.id.in_(in_use), *vendor)) or 0
        return active, free, busy

    d_active, d_free, d_busy = resources(Driver, Trip.driver_id)
    v_active, v_free, v_busy = resources(Vehicle, Trip.vehicle_id)
    return {
        "range_label": f.label,
        "cards": {
            "total_trips": total, "upcoming": upcoming, "assigned": assigned,
            "pending_assignment": scheduled,  # Operator requests waiting for a Vendor Admin to assign driver + vehicle
            "accepted": accepted, "ongoing": started, "completed": completed, "cancelled": cancelled,
            "total_passengers": pax, "capacity_utilization": _pct(need, seats), "escort_trips": escorts,
            "sms_sent": sms.get("sent", 0) + sms.get("delivered", 0), "sms_failed": sms.get("failed", 0),
            "sms_pending": sms.get("pending", 0),
        },
        "resources_now": {
            "drivers_active": d_active, "drivers_available": d_free, "drivers_in_use": d_busy,
            "vehicles_active": v_active, "vehicles_available": v_free, "vehicles_in_use": v_busy,
        },
    }


# ------------------------------------------------------------------ charts
def breakdown(db: Session, f: Filters, include_vendors: bool) -> dict:
    cond, g = trip_cond(f), get_settings()
    statuses = dict(db.execute(select(Trip.status, func.count()).where(*cond).group_by(Trip.status)).all())
    local_ts = func.timezone(g.business_timezone, Trip.scheduled_start)
    hour_expr, day_expr = func.extract("hour", local_ts), func.date_trunc("day", local_ts)
    hourly = {int(h): c for h, c in db.execute(select(hour_expr, func.count()).where(*cond, NOT_CANCELLED).group_by(hour_expr)).all()}
    daily = db.execute(select(day_expr, func.count()).where(*cond, NOT_CANCELLED).group_by(day_expr).order_by(day_expr)).all()
    shift_name = func.coalesce(ShiftDefinition.name, "No shift")
    by_shift = db.execute(
        select(shift_name, func.count()).select_from(Trip)
        .outerjoin(ShiftDefinition, ShiftDefinition.id == Trip.shift_id).where(*cond, NOT_CANCELLED)
        .group_by(shift_name).order_by(func.count().desc())).all()
    by_customer = db.execute(
        select(Customer.name, func.count()).select_from(Trip).join(Customer, Customer.id == Trip.customer_id)
        .where(*cond, NOT_CANCELLED).group_by(Customer.name).order_by(func.count().desc()).limit(10)).all()
    by_vendor = db.execute(
        select(Vendor.name, func.count()).select_from(Trip).join(Vendor, Vendor.id == Trip.vendor_id)
        .where(*cond, NOT_CANCELLED).group_by(Vendor.name).order_by(func.count().desc())).all() if include_vendors else []

    planned = sum(c for s, c in statuses.items() if s != TripStatus.CANCELLED)
    completed = statuses.get(TripStatus.COMPLETED, 0)
    grace = timedelta(minutes=g.on_time_grace_minutes)
    started = db.execute(
        select(func.count(), func.count().filter(Trip.started_at > Trip.scheduled_start + grace),
               func.avg(func.extract("epoch", Trip.started_at - Trip.scheduled_start) / 60).filter(Trip.started_at > Trip.scheduled_start + grace))
        .where(*cond, Trip.started_at.is_not(None))).one()
    return {
        "status": [{"status": s.value, "count": statuses.get(s, 0)} for s in TripStatus if s != TripStatus.SCHEDULED or statuses.get(s)],
        "hourly": [{"hour": h, "count": int(hourly.get(h, 0))} for h in range(24)],
        "daily": [{"date": d.date().isoformat(), "count": c} for d, c in daily],
        "by_shift": [{"name": n, "count": c} for n, c in by_shift],
        "by_customer": [{"name": n, "count": c} for n, c in by_customer],
        "by_vendor": [{"name": n, "count": c} for n, c in by_vendor],
        "completed_vs_planned": {"planned": planned, "completed": completed, "completion_rate": _pct(completed, planned)},
        "punctuality": {"started": started[0], "late": started[1], "on_time": started[0] - started[1],
                        "avg_delay_minutes": round(float(started[2] or 0), 1), "grace_minutes": g.on_time_grace_minutes,
                        "on_time_rate": _pct(started[0] - started[1], started[0])},
    }


def _minutes(): return func.extract("epoch", Trip.scheduled_end - Trip.scheduled_start) / 60


def driver_utilization(db: Session, f: Filters, limit: int | None = None) -> list[dict]:
    on = and_(Trip.driver_id == Driver.id, NOT_CANCELLED, *trip_cond(f))
    q = (select(Driver, func.count(Trip.id), func.count(Trip.id).filter(Trip.status == TripStatus.COMPLETED),
                func.coalesce(func.sum(_minutes()), 0), func.coalesce(func.sum(Trip.passenger_count), 0))
         .outerjoin(Trip, on).group_by(Driver.id)
         .order_by(func.count(Trip.id).desc(), Driver.first_name))
    if f.vendor_id is not None:
        q = q.where(Driver.vendor_id == f.vendor_id)
    if limit:
        q = q.limit(limit)
    return [{"id": d.id, "code": d.code, "name": f"{d.first_name} {d.last_name}", "status": d.status.value, "trips": t,
             "completed": c, "booked_hours": round(float(m) / 60, 1), "passengers": int(p)}
            for d, t, c, m, p in db.execute(q).all()]


def vehicle_utilization(db: Session, f: Filters, limit: int | None = None) -> list[dict]:
    on = and_(Trip.vehicle_id == Vehicle.id, NOT_CANCELLED, *trip_cond(f))
    q = (select(Vehicle, func.count(Trip.id), func.count(Trip.id).filter(Trip.status == TripStatus.COMPLETED),
                func.coalesce(func.sum(_minutes()), 0), func.coalesce(func.sum(Trip.required_capacity), 0),
                func.coalesce(func.sum(Trip.passenger_count), 0))
         .outerjoin(Trip, on).group_by(Vehicle.id).order_by(func.count(Trip.id).desc(), Vehicle.vehicle_number))
    if f.vendor_id is not None:
        q = q.where(Vehicle.vendor_id == f.vendor_id)
    if limit:
        q = q.limit(limit)
    return [{"id": v.id, "code": v.code, "vehicle_number": v.vehicle_number, "model": v.model, "capacity": v.capacity,
             "status": v.status.value, "trips": t, "completed": c, "booked_hours": round(float(m) / 60, 1),
             "passengers": int(p), "seat_utilization": _pct(need, t * v.capacity) if t else 0.0}
            for v, t, c, m, need, p in db.execute(q).all()]


# ------------------------------------------------------------------ exceptions
def exceptions(db: Session, f: Filters) -> list[dict]:
    """Trips that need an operator's attention right now (within the dashboard filters)."""
    g, now = get_settings(), _now()
    cond = trip_cond(f)
    grace = timedelta(minutes=g.on_time_grace_minutes)
    out: list[dict] = []

    def add(rows, code, message):
        for t in rows:
            out.append({"trip_id": t.id, "code": t.code, "reason": code, "message": message(t),
                        "scheduled_start": t.scheduled_start.astimezone(timezone.utc).isoformat()})

    base = select(Trip).where(*cond)
    add(db.scalars(base.where(Trip.status.in_((TripStatus.ASSIGNED, TripStatus.ACCEPTED)), Trip.scheduled_start < now - grace)
                   .order_by(Trip.scheduled_start).limit(20)), "not_started",
        lambda t: f"{t.code} should have started at {t.scheduled_start.astimezone(tz()):%H:%M} but is still {t.status.value}")
    add(db.scalars(base.where(Trip.status == TripStatus.STARTED, Trip.scheduled_end < now).order_by(Trip.scheduled_end).limit(20)),
        "running_late", lambda t: f"{t.code} is past its scheduled end ({t.scheduled_end.astimezone(tz()):%H:%M}) and not completed")
    soon = now + timedelta(minutes=g.acceptance_warning_minutes)
    add(db.scalars(base.where(Trip.status == TripStatus.ASSIGNED, Trip.scheduled_start >= now,
                              Trip.scheduled_start <= soon).order_by(Trip.scheduled_start).limit(20)),
        "awaiting_acceptance", lambda t: f"{t.code} departs within {g.acceptance_warning_minutes} min and the driver hasn't accepted")
    # requests nobody has assigned yet, and the departure time is close (or already past)
    near = now + timedelta(minutes=g.assignment_warning_minutes)
    add(db.scalars(base.where(Trip.status == TripStatus.SCHEDULED, Trip.scheduled_start <= near)
                   .order_by(Trip.scheduled_start).limit(20)),
        "unassigned", lambda t: f"{t.code} departs {'at ' + t.scheduled_start.astimezone(tz()).strftime('%H:%M') if t.scheduled_start > now else 'already passed'} and has no driver or vehicle yet")
    add(db.scalars(base.join(Driver, Driver.id == Trip.driver_id).where(Trip.status.in_(OPEN), Trip.scheduled_end >= now,
                                                                      Driver.status != ActiveStatus.ACTIVE).limit(20)),
        "driver_inactive", lambda t: f"{t.code} is assigned to a driver who is now inactive")
    add(db.scalars(base.join(Vehicle, Vehicle.id == Trip.vehicle_id).where(Trip.status.in_(OPEN), Trip.scheduled_end >= now,
                                                                         Vehicle.status != ActiveStatus.ACTIVE).limit(20)),
        "vehicle_inactive", lambda t: f"{t.code} is assigned to a vehicle that is now inactive")
    add(db.scalars(base.join(Vehicle, Vehicle.id == Trip.vehicle_id).where(Trip.status.in_(OPEN), Trip.scheduled_end >= now,
                                                                         Vehicle.capacity < Trip.required_capacity).limit(20)),
        "capacity_conflict", lambda t: f"{t.code} needs {t.required_capacity} seats but its vehicle now seats fewer")
    skipped = select(TripPassenger.trip_id).where(TripPassenger.not_dropped_at.is_not(None))
    add(db.scalars(base.where(Trip.id.in_(skipped)).order_by(Trip.scheduled_start.desc()).limit(20)),
        "not_dropped", lambda t: f"{t.code} had employees the driver marked as not dropped. Open the trip to see why")
    failed = select(SmsLog.trip_id).where(SmsLog.status == "failed", SmsLog.trip_id.is_not(None))
    add(db.scalars(base.where(Trip.id.in_(failed)).order_by(Trip.scheduled_start.desc()).limit(20)),
        "sms_failed", lambda t: f"{t.code} has SMS that failed to send")
    return out


# ------------------------------------------------------------------ SMS
def sms_stats(db: Session, f: Filters) -> dict:
    ids = select(Trip.id).where(*trip_cond(f))
    by_status = dict(db.execute(select(SmsLog.status, func.count()).where(SmsLog.trip_id.in_(ids)).group_by(SmsLog.status)).all())
    by_template = db.execute(select(SmsLog.template, func.count()).where(SmsLog.trip_id.in_(ids)).group_by(SmsLog.template)
                             .order_by(func.count().desc())).all()
    total = sum(by_status.values())
    ok = by_status.get("sent", 0) + by_status.get("delivered", 0)
    return {"total": total, "by_status": by_status, "success_rate": _pct(ok, total),
            "by_template": [{"template": t, "count": c} for t, c in by_template]}

