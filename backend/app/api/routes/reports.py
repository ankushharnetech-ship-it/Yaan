"""Reports (spec 18). Every report is JSON for the screen and .xlsx on request, from the same builder, so the
download always matches what was on screen."""
from datetime import date, datetime, timedelta, timezone
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.api.routes.trips import _maps, _serialize
from app.core.config import get_settings
from app.api.routes.expenses import _out as expenses_out
from app.core.permissions import has_permission
from app.core.timeutil import local_date, to_local
from app.db.session import get_db
from app.models import Customer, Driver, Expense, SmsLog, Trip, TripStatus, User, Vehicle, Vendor
from app.services import analytics as an, audit, compliance as svc_compliance

router = APIRouter(prefix="/reports", tags=["reports"])
MAX_ROWS = 5000

CATALOG = [
    {"key": "trips", "title": "Trip summary", "description": "Every trip in the period with its status."},
    {"key": "completed-trips", "title": "Completed trips", "description": "Trips that were completed."},
    {"key": "cancelled-trips", "title": "Cancelled trips", "description": "Cancelled trips with who cancelled and why."},
    {"key": "drivers", "title": "Driver utilization", "description": "Trips, booked hours and passengers per driver."},
    {"key": "vehicles", "title": "Vehicle utilization", "description": "Trips, booked hours and seat use per vehicle."},
    {"key": "capacity", "title": "Capacity utilization", "description": "Seats used versus vehicle capacity, trip by trip."},
    {"key": "resources", "title": "Resource availability", "description": "Every driver and vehicle: bookings in the period and whether free right now."},
    {"key": "customers", "title": "Customer-wise trips", "description": "Trip counts per customer."},
    {"key": "vendors", "title": "Vendor-wise trips", "description": "Trip counts per vendor.", "super_admin_only": True},
    {"key": "compliance-drivers", "title": "Driver compliance", "description": "Every active driver document with its expiry status (not limited to the period)."},
    {"key": "compliance-vehicles", "title": "Vehicle compliance", "description": "Every active vehicle document with its expiry status (not limited to the period)."},
    {"key": "expenses", "title": "Expenses", "description": "Every expense in the period with who entered it.", "admin_only": True},
    {"key": "notifications", "title": "SMS success / failure", "description": "Daily SMS outcomes for trips in the period."},
]


def report_filters(
    range: str = Query("this_month"), date_from: date | None = None, date_to: date | None = None,
    vendor_id: int | None = None, customer_id: int | None = None, site_id: int | None = None,
    scope: VendorScope = Depends(get_vendor_scope),
) -> an.Filters:
    start, end, label = an.resolve_range(range, date_from, date_to)
    return an.Filters(start, end, label, vendor_id if scope.is_global else scope.vendor_id, customer_id, site_id)


def col(key: str, label: str, width: int = 16) -> dict:
    return {"key": key, "label": label, "width": width}


def stamp(dt: datetime | None) -> str:
    return to_local(dt).strftime("%Y-%m-%d %H:%M") if dt else ""


# ------------------------------------------------------------------ builders
def _trip_rows(db: Session, f: an.Filters, user: User, statuses=None) -> tuple[list[Trip], dict, bool]:
    q = select(Trip).where(*an.trip_cond(f))
    if statuses:
        q = q.where(Trip.status.in_(statuses))
    rows = db.scalars(q.order_by(Trip.scheduled_start, Trip.id).limit(MAX_ROWS + 1)).all()
    truncated = len(rows) > MAX_ROWS
    rows = rows[:MAX_ROWS]
    return rows, _maps(db, rows), truncated


def trips_report(db, f, user, scope, statuses=None, cancelled=False, title="Trip summary"):
    rows, m, trunc = _trip_rows(db, f, user, statuses)
    s = [_serialize(t, m, user) for t in rows]
    cols = [col("code", "Trip ID", 14), col("date", "Date", 12), col("start", "Start", 10), col("end", "End", 10),
            col("customer", "Customer", 22), col("site", "Site", 18), col("type", "Type", 10), col("shift", "Shift", 14),
            col("passengers", "Passengers", 11), col("escort", "Escort seat", 11), col("driver", "Driver", 20),
            col("vehicle", "Vehicle", 14), col("status", "Status", 12), col("sms", "SMS", 10), col("created_by", "Created by", 18)]
    if cancelled:
        cols += [col("cancelled_by", "Cancelled by", 18), col("cancelled_at", "Cancelled at", 17), col("reason", "Reason", 30)]
    else:
        cols.append(col("completed_at", "Completed at", 17))
    out = []
    for t, d in zip(rows, s):
        r = {"code": d["code"], "date": stamp(t.scheduled_start)[:10], "start": stamp(t.scheduled_start)[11:],
             "end": stamp(t.scheduled_end)[11:], "customer": d["customer_name"], "site": d["site_name"], "type": d["trip_type"],
             "shift": d["shift_name"] or "", "passengers": t.passenger_count, "escort": "Yes" if t.escort_required else "No",
             "driver": d["driver_name"] or "", "vehicle": d["vehicle_number"] or "",
             "status": "Awaiting assignment" if t.status == TripStatus.SCHEDULED else t.status.value.title(),
             "sms": (d["sms_status"] or "").title(), "created_by": d["created_by"]}
        if cancelled:
            r.update(cancelled_by=d["cancelled_by"] or "", cancelled_at=stamp(t.cancelled_at), reason=t.cancellation_reason or "")
        else:
            r["completed_at"] = stamp(t.completed_at)
        out.append(r)
    by = {}
    for t in rows:
        by[t.status.value] = by.get(t.status.value, 0) + 1
    return {"title": title, "columns": cols, "rows": out, "truncated": trunc,
            "summary": {"Trips": len(rows), **{k.title(): v for k, v in sorted(by.items())}}}


def drivers_report(db, f, user, scope):
    data = an.driver_utilization(db, f)
    cols = [col("code", "Driver ID", 12), col("name", "Driver", 24), col("status", "Status", 10), col("trips", "Trips", 8),
            col("completed", "Completed", 11), col("booked_hours", "Booked hours", 13), col("passengers", "Passengers", 12)]
    rows = [{**d, "status": d["status"].title()} for d in data]
    return {"title": "Driver utilization", "columns": cols, "rows": rows,
            "summary": {"Drivers": len(rows), "Trips": sum(r["trips"] for r in rows),
                        "Booked hours": round(sum(r["booked_hours"] for r in rows), 1),
                        "Drivers with no trips": sum(1 for r in rows if not r["trips"])}}


def vehicles_report(db, f, user, scope):
    data = an.vehicle_utilization(db, f)
    cols = [col("code", "Vehicle ID", 12), col("vehicle_number", "Number", 14), col("model", "Vehicle Name", 18), col("capacity", "Seats", 8),
            col("status", "Status", 10), col("trips", "Trips", 8), col("completed", "Completed", 11),
            col("booked_hours", "Booked hours", 13), col("passengers", "Passengers", 12), col("seat_utilization", "Seat use %", 11)]
    rows = [{**d, "status": d["status"].title()} for d in data]
    used = [r["seat_utilization"] for r in rows if r["trips"]]
    return {"title": "Vehicle utilization", "columns": cols, "rows": rows,
            "summary": {"Vehicles": len(rows), "Trips": sum(r["trips"] for r in rows),
                        "Average seat use %": round(sum(used) / len(used), 1) if used else 0}}


def capacity_report(db, f, user, scope):
    q = (select(Trip, Vehicle).join(Vehicle, Vehicle.id == Trip.vehicle_id)
         .where(*an.trip_cond(f), an.NOT_CANCELLED).order_by(Trip.scheduled_start, Trip.id).limit(MAX_ROWS + 1))
    pairs = db.execute(q).all()
    trunc = len(pairs) > MAX_ROWS
    cols = [col("code", "Trip ID", 14), col("date", "Date", 12), col("vehicle", "Vehicle", 14), col("capacity", "Seats", 8),
            col("passengers", "Passengers", 11), col("escort", "Escort seat", 11), col("required", "Seats needed", 13),
            col("free", "Free seats", 11), col("util", "Utilization %", 14)]
    rows = [{"code": t.code, "date": stamp(t.scheduled_start)[:10], "vehicle": v.vehicle_number, "capacity": v.capacity,
             "passengers": t.passenger_count, "escort": "Yes" if t.escort_required else "No", "required": t.required_capacity,
             "free": v.capacity - t.required_capacity, "util": round(100 * t.required_capacity / v.capacity, 1)}
            for t, v in pairs[:MAX_ROWS]]
    seats = sum(r["capacity"] for r in rows)
    return {"title": "Capacity utilization", "columns": cols, "rows": rows, "truncated": trunc,
            "summary": {"Trips": len(rows), "Overall utilization %": round(100 * sum(r["required"] for r in rows) / seats, 1) if seats else 0}}


def resources_report(db, f, user, scope):
    now = datetime.now(timezone.utc)
    busy_d = set(db.scalars(select(Trip.driver_id).where(an.NOT_CANCELLED, Trip.scheduled_start <= now, Trip.block_end > now)))
    busy_v = set(db.scalars(select(Trip.vehicle_id).where(an.NOT_CANCELLED, Trip.scheduled_start <= now, Trip.block_end > now)))
    rows = []
    for d in an.driver_utilization(db, f):
        free = d["status"] == "active" and d["id"] not in busy_d
        rows.append({"kind": "Driver", "ref": d["code"], "name": d["name"], "capacity": "", "status": d["status"].title(),
                     "trips": d["trips"], "booked_hours": d["booked_hours"], "free_now": "Yes" if free else "No"})
    for v in an.vehicle_utilization(db, f):
        free = v["status"] == "active" and v["id"] not in busy_v
        rows.append({"kind": "Vehicle", "ref": v["code"], "name": f"{v['vehicle_number']} ({v['model']})", "capacity": v["capacity"],
                     "status": v["status"].title(), "trips": v["trips"], "booked_hours": v["booked_hours"], "free_now": "Yes" if free else "No"})
    cols = [col("kind", "Type", 9), col("ref", "ID", 12), col("name", "Name", 30), col("capacity", "Seats", 8), col("status", "Status", 10),
            col("trips", "Trips in period", 15), col("booked_hours", "Booked hours", 13), col("free_now", "Free now", 10)]
    return {"title": "Resource availability", "columns": cols, "rows": rows,
            "summary": {"Drivers free now": sum(1 for r in rows if r["kind"] == "Driver" and r["free_now"] == "Yes"),
                        "Vehicles free now": sum(1 for r in rows if r["kind"] == "Vehicle" and r["free_now"] == "Yes")}}


def customers_report(db, f, user, scope):
    q = (select(Customer.name, func.count().filter(an.NOT_CANCELLED), func.count().filter(Trip.status == TripStatus.COMPLETED),
                func.count().filter(Trip.status == TripStatus.CANCELLED),
                func.coalesce(func.sum(Trip.passenger_count).filter(an.NOT_CANCELLED), 0))
         .select_from(Trip).join(Customer, Customer.id == Trip.customer_id).where(*an.trip_cond(f))
         .group_by(Customer.name).order_by(func.count().desc()))
    rows = [{"name": n, "trips": t, "completed": c, "cancelled": x, "passengers": int(p)} for n, t, c, x, p in db.execute(q).all()]
    cols = [col("name", "Customer", 28), col("trips", "Trips (not cancelled)", 20), col("completed", "Completed", 11),
            col("cancelled", "Cancelled", 11), col("passengers", "Passengers", 12)]
    return {"title": "Customer-wise trips", "columns": cols, "rows": rows,
            "summary": {"Customers": len(rows), "Trips": sum(r["trips"] for r in rows)}}


def vendors_report(db, f, user, scope):
    if not scope.is_global:
        raise HTTPException(403, "You do not have permission to do this")
    q = (select(Vendor.name, func.count().filter(an.NOT_CANCELLED), func.count().filter(Trip.status == TripStatus.COMPLETED),
                func.count().filter(Trip.status == TripStatus.CANCELLED),
                func.coalesce(func.sum(Trip.passenger_count).filter(an.NOT_CANCELLED), 0))
         .select_from(Trip).join(Vendor, Vendor.id == Trip.vendor_id).where(*an.trip_cond(f))
         .group_by(Vendor.name).order_by(func.count().desc()))
    rows = [{"name": n, "trips": t, "completed": c, "cancelled": x, "passengers": int(p)} for n, t, c, x, p in db.execute(q).all()]
    cols = [col("name", "Vendor", 28), col("trips", "Trips (not cancelled)", 20), col("completed", "Completed", 11),
            col("cancelled", "Cancelled", 11), col("passengers", "Passengers", 12)]
    return {"title": "Vendor-wise trips", "columns": cols, "rows": rows,
            "summary": {"Vendors": len(rows), "Trips": sum(r["trips"] for r in rows)}}


def notifications_report(db, f, user, scope):
    ids = select(Trip.id).where(*an.trip_cond(f))
    day = func.date_trunc("day", func.timezone(get_settings().business_timezone, SmsLog.created_at))
    data: dict = {}
    for d, st, n in db.execute(select(day, SmsLog.status, func.count()).where(SmsLog.trip_id.in_(ids)).group_by(day, SmsLog.status).order_by(day)):
        data.setdefault(d.date().isoformat(), {})[st] = n
    rows = []
    for d, c in data.items():
        total = sum(c.values())
        rows.append({"date": d, "total": total, "sent": c.get("sent", 0), "delivered": c.get("delivered", 0),
                     "failed": c.get("failed", 0), "pending": c.get("pending", 0),
                     "success": round(100 * (c.get("sent", 0) + c.get("delivered", 0)) / total, 1) if total else 0})
    cols = [col("date", "Date", 12), col("total", "Messages", 11), col("sent", "Sent", 8), col("delivered", "Delivered", 11),
            col("failed", "Failed", 8), col("pending", "Pending", 9), col("success", "Success %", 11)]
    tot = sum(r["total"] for r in rows)
    ok = sum(r["sent"] + r["delivered"] for r in rows)
    return {"title": "SMS success / failure", "columns": cols, "rows": rows,
            "summary": {"Messages": tot, "Failed": sum(r["failed"] for r in rows), "Success %": round(100 * ok / tot, 1) if tot else 0}}


def _compliance_report(subject: str):
    def build(db, f, user, scope):
        rows = svc_compliance.load(db, subject, f.vendor_id)
        ids = {r.item.driver_id or r.item.vehicle_id for r in rows}
        if subject == "driver":
            names = {d.id: f"{d.first_name} {d.last_name}" for d in db.scalars(select(Driver).where(Driver.id.in_(ids)))} if ids else {}
        else:
            names = {v.id: v.vehicle_number for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(ids)))} if ids else {}
        types = svc_compliance.doc_type_names(db, f"{subject}_doc_type")
        label = {"expired": "Expired", "expiring": "About to expire", "valid": "Valid"}
        out = [{"subject": names.get(r.item.driver_id or r.item.vehicle_id, ""), "doc": types.get(r.item.doc_type_id, ""),
                "title": r.item.title or "", "reference": r.item.reference_number or "",
                "issued": r.item.issue_date.isoformat() if r.item.issue_date else "", "expiry": r.item.expiry_date.isoformat(),
                "days_left": r.days_left, "state": label[r.state]} for r in rows]
        cols = [col("subject", "Driver" if subject == "driver" else "Vehicle", 22), col("doc", "Document", 22),
                col("title", "Title", 20), col("reference", "Reference", 18), col("issued", "Issued", 12),
                col("expiry", "Expires", 12), col("days_left", "Days left", 10), col("state", "Status", 16)]
        n = lambda s: sum(r.state == s for r in rows)  # noqa: E731
        return {"title": f"{'Driver' if subject == 'driver' else 'Vehicle'} compliance", "columns": cols, "rows": out,
                "summary": {"Documents": len(rows), "Valid": n("valid"), "About to expire": n("expiring"), "Expired": n("expired")}}
    return build


def expenses_report(db, f, user, scope):
    if not has_permission(user.role, "expense:summary"):
        raise HTTPException(403, "You do not have permission to do this")
    first, last = local_date(f.start), local_date(f.end - timedelta(seconds=1))
    q = (select(Expense).where(Expense.expense_date >= first, Expense.expense_date <= last)
         .order_by(Expense.expense_date, Expense.id).limit(MAX_ROWS + 1))
    if f.vendor_id is not None:
        q = q.where(Expense.vendor_id == f.vendor_id)
    rows = list(db.scalars(q))
    trunc, rows = len(rows) > MAX_ROWS, rows[:MAX_ROWS]
    items = {i["id"]: i for i in expenses_out(db, rows, user, scope)}
    cols = [col("code", "Expense ID", 13), col("date", "Date", 12), col("category", "Category", 22), col("amount", "Amount (INR)", 14),
            col("payment", "Payment", 16), col("vehicle", "Vehicle", 14), col("driver", "Driver", 20), col("by", "Entered by", 20),
            col("role", "Role", 13), col("description", "Description", 36), col("status", "Status", 10)]
    out = [{"code": i["code"], "date": i["expense_date"], "category": i["category"], "amount": i["amount"],
            "payment": i["payment_method_label"], "vehicle": i["vehicle_number"] or "", "driver": i["driver_name"] or "",
            "by": i["entered_by"], "role": (i["entered_by_role"] or "").replace("_", " ").title(),
            "description": i["description"] or "", "status": i["status"].title() + (f" — {i['void_reason']}" if i["void_reason"] else "")}
           for i in items.values()]
    live = [i for i in items.values() if i["status"] == "recorded"]
    return {"title": "Expenses", "columns": cols, "rows": out, "truncated": trunc,
            "summary": {"Expenses": len(live), "Total (INR)": round(sum(i["amount"] for i in live), 2),
                        "Voided": len(items) - len(live)}}


BUILDERS = {
    "expenses": expenses_report,
    "compliance-drivers": _compliance_report("driver"), "compliance-vehicles": _compliance_report("vehicle"),
    "trips": lambda *a: trips_report(*a),
    "completed-trips": lambda *a: trips_report(*a, statuses=[TripStatus.COMPLETED], title="Completed trips"),
    "cancelled-trips": lambda *a: trips_report(*a, statuses=[TripStatus.CANCELLED], cancelled=True, title="Cancelled trips"),
    "drivers": drivers_report, "vehicles": vehicles_report, "capacity": capacity_report, "resources": resources_report,
    "customers": customers_report, "vendors": vendors_report, "notifications": notifications_report,
}


# ------------------------------------------------------------------ xlsx
def to_xlsx(rep: dict, period: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = rep["title"][:31]
    ws["A1"] = f"YAAN — {rep['title']}"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A2"] = f"Period: {period}   Â·   Generated {to_local(datetime.now(timezone.utc)):%Y-%m-%d %H:%M}"
    r = 3
    for k, v in rep["summary"].items():
        ws.cell(row=r, column=1, value=k).font = Font(bold=True)
        ws.cell(row=r, column=2, value=v)
        r += 1
    head = r + 1
    fill = PatternFill("solid", fgColor="0F766E")
    for i, c in enumerate(rep["columns"], 1):
        cell = ws.cell(row=head, column=i, value=c["label"])
        cell.font, cell.fill, cell.alignment = Font(bold=True, color="FFFFFF"), fill, Alignment(vertical="center")
        ws.column_dimensions[get_column_letter(i)].width = max(c["width"], len(c["label"]) + 2)
    for ri, row in enumerate(rep["rows"], head + 1):
        for ci, c in enumerate(rep["columns"], 1):
            v = row.get(c["key"], "")
            cell = ws.cell(row=ri, column=ci, value=v)
            if isinstance(v, str) and v.startswith("="):
                cell.data_type = "s"  # user-entered text like "=HYPERLINK(...)" must never run as a formula
    ws.freeze_panes = ws.cell(row=head + 1, column=1)
    if rep["rows"]:
        ws.auto_filter.ref = f"A{head}:{get_column_letter(len(rep['columns']))}{head + len(rep['rows'])}"
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ------------------------------------------------------------------ routes
@router.get("")
def catalog(user: User = Depends(require_permission("report:read")), scope: VendorScope = Depends(get_vendor_scope)):
    admin = has_permission(user.role, "expense:summary")
    return {"items": [c for c in CATALOG if (scope.is_global or not c.get("super_admin_only")) and (admin or not c.get("admin_only"))]}


@router.get("/{name}")
def run_report(name: str, format: str = Query("json", pattern="^(json|xlsx)$"), f: an.Filters = Depends(report_filters),
               user: User = Depends(require_permission("report:read")), scope: VendorScope = Depends(get_vendor_scope),
               db: Session = Depends(get_db)):
    if name not in BUILDERS:
        raise HTTPException(404, "Unknown report")
    rep = BUILDERS[name](db, f, user, scope)
    rep.setdefault("truncated", False)
    rep["period"] = f.label
    if format == "json":
        return rep
    audit.record(db, "report.exported", user, entity_type="report", entity_id=name, vendor_id=f.vendor_id,
                 detail={"period": f.label, "rows": len(rep["rows"])})
    db.commit()
    fname = f"yaan-{name}-{datetime.now(timezone.utc):%Y%m%d}.xlsx"
    return Response(to_xlsx(rep, f.label), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{fname}"'})
