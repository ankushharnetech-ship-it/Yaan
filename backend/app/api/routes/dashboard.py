from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.api.routes.trips import _maps, _serialize
from app.db.session import get_db
from app.models import Trip, TripStatus, User
from app.services import analytics as an

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def dash_filters(
    range: str = Query("today", description="today | tomorrow | this_week | this_month | custom"),
    date_from: date | None = None, date_to: date | None = None,
    vendor_id: int | None = None, customer_id: int | None = None, site_id: int | None = None,
    status: TripStatus | None = None, trip_type_id: int | None = None, shift_id: int | None = None,
    scope: VendorScope = Depends(get_vendor_scope),
) -> an.Filters:
    start, end, label = an.resolve_range(range, date_from, date_to)
    # Vendor-scoped users are pinned to their own vendor; only a Super Admin may choose (or leave unset = all).
    vid = vendor_id if scope.is_global else scope.vendor_id
    return an.Filters(start, end, label, vid, customer_id, site_id, status, trip_type_id, shift_id)


@router.get("/summary")
def summary(f: an.Filters = Depends(dash_filters), _: User = Depends(require_permission("dashboard:view")),
            db: Session = Depends(get_db)):
    return an.summary(db, f)


@router.get("/status-breakdown")
def status_breakdown(f: an.Filters = Depends(dash_filters), user: User = Depends(require_permission("dashboard:view")),
                     scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    return an.breakdown(db, f, include_vendors=scope.is_global)


@router.get("/resource-utilization")
def resource_utilization(f: an.Filters = Depends(dash_filters), _: User = Depends(require_permission("dashboard:view")),
                         db: Session = Depends(get_db)):
    return {"drivers": an.driver_utilization(db, f, limit=8), "vehicles": an.vehicle_utilization(db, f, limit=8)}


@router.get("/upcoming")
def upcoming(f: an.Filters = Depends(dash_filters), hours: int = Query(24, ge=1, le=168),
             user: User = Depends(require_permission("dashboard:view")), db: Session = Depends(get_db)):
    """Compact operational lists. 'Upcoming' looks `hours` ahead from now, regardless of the date filter."""
    now = datetime.now(timezone.utc)
    other = [c for c in an.trip_cond(f)[2:]]  # keep vendor/customer/site/... filters, drop the date window

    def rows(*conds, order, limit=10):
        ts = db.scalars(select(Trip).where(*other, *conds).order_by(*order).limit(limit)).all()
        m = _maps(db, list(ts))
        return [_serialize(t, m, user) for t in ts]

    return {
        "window_hours": hours,
        "upcoming": rows(Trip.status.in_(an.OPEN), Trip.scheduled_end >= now, Trip.scheduled_start <= now + timedelta(hours=hours),
                         order=(Trip.scheduled_start.asc(),)),
        "ongoing": rows(Trip.status == TripStatus.STARTED, order=(Trip.scheduled_start.asc(),)),
        "awaiting_assignment": rows(Trip.status == TripStatus.SCHEDULED, Trip.scheduled_end >= now,
                                    order=(Trip.scheduled_start.asc(),)),
        "awaiting_acceptance": rows(Trip.status == TripStatus.ASSIGNED, Trip.scheduled_end >= now,
                                    order=(Trip.scheduled_start.asc(),)),
        "recently_completed": rows(Trip.status == TripStatus.COMPLETED, order=(Trip.completed_at.desc().nulls_last(),)),
    }


@router.get("/exceptions")
def exceptions(f: an.Filters = Depends(dash_filters), _: User = Depends(require_permission("dashboard:view")),
               db: Session = Depends(get_db)):
    return {"items": an.exceptions(db, f)}


@router.get("/notifications")
def notifications(f: an.Filters = Depends(dash_filters), _: User = Depends(require_permission("dashboard:view")),
                  db: Session = Depends(get_db)):
    return an.sms_stats(db, f)
