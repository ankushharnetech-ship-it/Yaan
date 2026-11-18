from datetime import datetime, timedelta, timezone
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import AuditLog
from app.services import analytics as an
from tests.conftest import CONTACT, GEO, auth, make_user, verify_all_otps
from tests.test_trips import BASE, create, driver_world, iso, lk, trip_body, w  # noqa: F401  (fixtures)

DAY = "range=custom&date_from=2030-01-07&date_to=2030-01-07"   # BASE (09:00 UTC) is 14:30 IST on this day
IST = ZoneInfo("Asia/Kolkata")


def backdate(db, trip_id: int, start_min: int, end_min: int) -> None:
    """Moves an existing trip to `now + minutes` (the booking API itself never accepts a past start)."""
    from sqlalchemy import text
    db.execute(text("update trips set scheduled_start = now() + make_interval(mins => :s), scheduled_end = now() + make_interval(mins => :e),"
                    " block_end = now() + make_interval(mins => :e + 30) where id = :i"), {"s": start_min, "e": end_min, "i": trip_id})
    db.commit()


def get(w, path, who="oper_a", qs=DAY, **kw):
    sep = "&" if "?" in path else "?"
    return w.client.get(f"/api{path}{sep}{qs}", headers=w.h[who] if isinstance(who, str) else who, **kw)


def now_iso(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def busy(driver_world):
    """A day with every kind of trip."""
    w = driver_world
    st = lambda tid, s, h: w.client.post(f"/api/trips/{tid}/status", headers=h, json={"status": s})  # noqa: E731
    w.t_assigned = create(w, emps=[w.m1], start=0, end=60).json()                                       # d1 v4, 1 pax
    w.t_accepted = create(w, emps=[w.m2], driver=w.d2, vehicle=w.v6, start=0, end=60).json()            # d2 v6
    st(w.t_accepted["id"], "accepted", w.dh2)
    w.t_done = create(w, emps=[w.m1, w.f1], driver=w.d1, vehicle=w.v4, start=120, end=180).json()       # escort: 2+1 of 4 seats
    for s in ("accepted", "started"):
        st(w.t_done["id"], s, w.dh1)
    verify_all_otps(w.client, w.dh1, w.t_done["id"])
    st(w.t_done["id"], "completed", w.dh1)
    w.t_cancel = create(w, emps=[w.m3], driver=w.d2, vehicle=w.v3, start=120, end=180).json()
    w.client.post(f"/api/trips/{w.t_cancel['id']}/cancel", headers=w.h["admin_a"], json={"reason": "Employee on leave"})
    return w


# ---------------------------------------------------------------- ranges
def test_range_presets_use_monday_weeks():
    s, e, _ = an.resolve_range("this_week", None, None)
    assert s.astimezone(IST).weekday() == 0 and s.astimezone(IST).hour == 0 and e - s == timedelta(days=7)
    s, e, _ = an.resolve_range("this_month", None, None)
    assert s.astimezone(IST).day == 1 and e.astimezone(IST).day == 1
    t0, t1, _ = an.resolve_range("today", None, None)
    n0, n1, _ = an.resolve_range("tomorrow", None, None)
    assert t1 - t0 == timedelta(days=1) and n0 == t1 and t0 <= datetime.now(timezone.utc) < t1


def test_invalid_ranges_rejected(w):
    for qs in ("range=custom", "range=custom&date_from=2030-02-01&date_to=2030-01-01",
               "range=custom&date_from=2020-01-01&date_to=2030-01-01", "range=forever"):
        assert get(w, "/dashboard/summary", qs=qs).status_code == 422, qs


# ---------------------------------------------------------------- summary
def test_summary_cards(busy):
    w = busy
    c = get(w, "/dashboard/summary").json()["cards"]
    assert c["total_trips"] == 4 and c["assigned"] == 1 and c["accepted"] == 1
    assert c["ongoing"] == 0 and c["completed"] == 1 and c["cancelled"] == 1 and c["pending_assignment"] == 0
    assert c["total_passengers"] == 4                       # 1 + 1 + 2 (cancelled trip excluded)
    assert c["escort_trips"] == 1
    # seats needed 1 + 1 + 3 (2 pax + escort) = 5 of 4 + 6 + 4 = 14 seats
    assert c["capacity_utilization"] == pytest.approx(35.7, abs=0.1)
    assert c["sms_failed"] == 0 and c["sms_sent"] > 0


def test_upcoming_counts_open_future_trips_only(busy):
    c = get(busy, "/dashboard/summary").json()["cards"]
    assert c["upcoming"] == 2                               # assigned + accepted; completed/cancelled are not upcoming


def test_summary_filters(busy):
    w = busy
    other = w.post("/api/customers", {"code": "C2", "name": "Other Co", **GEO, **CONTACT})
    assert get(w, "/dashboard/summary", qs=DAY + f"&customer_id={other['id']}").json()["cards"]["total_trips"] == 0
    assert get(w, "/dashboard/summary", qs=DAY + f"&customer_id={w.customer['id']}").json()["cards"]["total_trips"] == 4
    assert get(w, "/dashboard/summary", qs=DAY + "&status=completed").json()["cards"]["total_trips"] == 1
    assert get(w, "/dashboard/summary", qs=DAY + f"&trip_type_id={w.pickup}").json()["cards"]["total_trips"] == 4
    nxt = "range=custom&date_from=2030-01-08&date_to=2030-01-08"
    assert get(w, "/dashboard/summary", qs=nxt).json()["cards"]["total_trips"] == 0


def test_sms_counts_failed(w, smsbox):
    smsbox.fail = "down"
    create(w)
    c = get(w, "/dashboard/summary").json()["cards"]
    assert c["sms_failed"] == 2 and c["sms_sent"] == 0
    s = get(w, "/dashboard/notifications").json()
    assert s["total"] == 2 and s["by_status"] == {"failed": 2} and s["success_rate"] == 0


def test_resources_now_reflect_current_bookings_and_buffer(w, db):
    r = get(w, "/dashboard/summary").json()["resources_now"]
    assert (r["drivers_active"], r["drivers_available"], r["drivers_in_use"]) == (2, 2, 0)
    assert (r["vehicles_active"], r["vehicles_available"], r["vehicles_in_use"]) == (3, 3, 0)
    # on a trip right now
    # The API refuses to book in the past, so book ahead and then move the trip into the past directly in the database.
    now_trip = trip_body(w, start=0, end=1)
    now_trip.update(scheduled_start=now_iso(60), scheduled_end=now_iso(120))
    made = w.client.post("/api/trips", headers=w.h["admin_a"], json=now_trip)
    assert made.status_code == 201
    backdate(db, made.json()["id"], -10, 50)
    r = get(w, "/dashboard/summary").json()["resources_now"]
    assert (r["drivers_available"], r["drivers_in_use"], r["vehicles_available"], r["vehicles_in_use"]) == (1, 1, 2, 1)
    # a trip that ended 10 minutes ago: not "in use", but still inside the 30-minute buffer so not available
    first_id = w.client.get("/api/trips", headers=w.h["admin_a"]).json()["items"][0]["id"]
    w.client.post(f"/api/trips/{first_id}/cancel", headers=w.h["admin_a"], json={"reason": "reset"})
    ended = trip_body(w, driver=w.d2, vehicle=w.v6)
    ended.update(scheduled_start=now_iso(60), scheduled_end=now_iso(120))
    made = w.client.post("/api/trips", headers=w.h["admin_a"], json=ended)
    assert made.status_code == 201
    backdate(db, made.json()["id"], -70, -10)
    r = get(w, "/dashboard/summary").json()["resources_now"]
    assert (r["drivers_in_use"], r["drivers_available"]) == (0, 1)
    # inactive resources are not counted
    w.client.patch(f"/api/drivers/{w.d1['id']}/status", headers=w.h["admin_a"], json={"status": "inactive"})
    assert get(w, "/dashboard/summary").json()["resources_now"]["drivers_active"] == 1


# ---------------------------------------------------------------- access
def test_dashboard_access_and_isolation(busy):
    w = busy
    for path in ("summary", "status-breakdown", "resource-utilization", "upcoming", "exceptions", "notifications"):
        assert get(w, f"/dashboard/{path}", who=w.dh1).status_code == 403, path       # drivers: no dashboard
        assert get(w, f"/dashboard/{path}", who="oper_a").status_code == 200, path
        assert get(w, f"/dashboard/{path}", who="admin_a").status_code == 200, path
    assert get(w, "/dashboard/summary", who="admin_b").json()["cards"]["total_trips"] == 0
    assert get(w, "/dashboard/summary", who="root").json()["cards"]["total_trips"] == 4
    # vendor admin cannot widen scope with vendor_id
    spoof = get(w, "/dashboard/summary", who="admin_b", qs=DAY + f"&vendor_id={w.world['va'].id}")
    assert spoof.json()["cards"]["total_trips"] == 0
    only_b = get(w, "/dashboard/summary", who="root", qs=DAY + f"&vendor_id={w.world['vb'].id}")
    assert only_b.json()["cards"]["total_trips"] == 0
    assert w.client.get("/api/dashboard/summary").status_code == 401


# ---------------------------------------------------------------- charts
def test_breakdown(busy):
    w = busy
    b = get(w, "/dashboard/status-breakdown").json()
    by = {x["status"]: x["count"] for x in b["status"]}
    assert by["assigned"] == 1 and by["accepted"] == 1 and by["completed"] == 1 and by["cancelled"] == 1 and by["started"] == 0
    hours = {h["hour"]: h["count"] for h in b["hourly"]}
    assert hours[14] == 2 and hours[16] == 1 and sum(hours.values()) == 3          # IST hours; cancelled excluded
    assert b["by_customer"] == [{"name": "Acme", "count": 3}] and b["by_shift"] == [{"name": "No shift", "count": 3}]
    assert b["completed_vs_planned"] == {"planned": 3, "completed": 1, "completion_rate": 33.3}
    assert b["punctuality"]["started"] == 1 and b["punctuality"]["late"] == 0       # started long before its 2030 schedule
    assert [v["name"] for v in b["by_vendor"]] == []                                 # vendor admins don't get vendor-wise
    assert get(w, "/dashboard/status-breakdown", who="root").json()["by_vendor"] == [{"name": "Alpha", "count": 3}]


def test_punctuality_flags_late_starts(w, db):
    t = create(w).json()
    from app.models import Trip
    row = db.get(Trip, t["id"])
    row.status = "started"
    row.started_at = row.scheduled_start + timedelta(minutes=20)
    db.commit()
    p = get(w, "/dashboard/status-breakdown").json()["punctuality"]
    assert p["late"] == 1 and p["on_time"] == 0 and p["avg_delay_minutes"] == 20.0
    row.started_at = row.scheduled_start + timedelta(minutes=4)                     # within the 5-minute grace
    db.commit()
    assert get(w, "/dashboard/status-breakdown").json()["punctuality"]["late"] == 0


def test_resource_utilization(busy):
    u = get(busy, "/dashboard/resource-utilization").json()
    d = {x["name"]: x for x in u["drivers"]}
    assert d["L1 D"]["trips"] == 2 and d["L1 D"]["completed"] == 1 and d["L1 D"]["booked_hours"] == 2.0 and d["L1 D"]["passengers"] == 3
    assert d["L2 D"]["trips"] == 1                                                  # its cancelled trip doesn't count
    v = {x["vehicle_number"]: x for x in u["vehicles"]}
    assert v["MH01AA0004"]["trips"] == 2 and v["MH01AA0004"]["seat_utilization"] == 50.0   # (1+3) of 2*4 seats
    assert v["MH01AA0003"]["trips"] == 0                                            # unused vehicles are listed too


# ---------------------------------------------------------------- lists & exceptions
def test_operational_lists(driver_world):
    w = driver_world
    soon = trip_body(w); soon.update(scheduled_start=now_iso(120), scheduled_end=now_iso(180))
    s = w.client.post("/api/trips", headers=w.h["admin_a"], json=soon).json()
    far = trip_body(w, driver=w.d2, vehicle=w.v6); far.update(scheduled_start=now_iso(60 * 60), scheduled_end=now_iso(60 * 61))
    w.client.post("/api/trips", headers=w.h["admin_a"], json=far)
    today = datetime.now(IST).date()
    qs = f"range=custom&date_from={today - timedelta(days=1)}&date_to={today + timedelta(days=5)}"
    u = get(w, "/dashboard/upcoming", qs=qs + "&hours=24").json()
    assert [t["id"] for t in u["upcoming"]] == [s["id"]]                             # the far trip is beyond 24h
    assert [t["id"] for t in u["awaiting_acceptance"]][0] == s["id"]
    w.client.post(f"/api/trips/{s['id']}/status", headers=w.dh1, json={"status": "accepted"})
    w.client.post(f"/api/trips/{s['id']}/status", headers=w.dh1, json={"status": "started"})
    u = get(w, "/dashboard/upcoming", qs=qs).json()
    assert [t["id"] for t in u["ongoing"]] == [s["id"]] and u["upcoming"] == []
    verify_all_otps(w.client, w.dh1, s["id"])
    w.client.post(f"/api/trips/{s['id']}/status", headers=w.dh1, json={"status": "completed"})
    assert get(w, "/dashboard/upcoming", qs=qs).json()["recently_completed"][0]["id"] == s["id"]
    assert get(w, "/dashboard/upcoming", who="admin_b", qs=qs).json()["recently_completed"] == []


def test_exceptions(driver_world, db):
    w = driver_world
    mk = lambda drv, veh, a, b, **kw: w.client.post("/api/trips", headers=w.h["admin_a"], json={  # noqa: E731
        **trip_body(w, driver=drv, vehicle=veh, **kw), "scheduled_start": now_iso(a), "scheduled_end": now_iso(b)}).json()
    late = mk(w.d1, w.v4, 60, 120)                                 # booked ahead (the API refuses past starts) ...
    backdate(db, late["id"], -120, -60)                           # ... then moved back: it should have started already
    soon = mk(w.d2, w.v6, 20, 80)                                  # leaves in 20 min, not accepted
    big = mk(w.d1, w.v3, 600, 660, emps=[w.m1, w.m2, w.m3])        # 3 pax in the 3-seater
    w.client.put(f"/api/vehicles/{w.v3['id']}", headers=w.h["admin_a"], json={
        "vehicle_number": "MH01AA0003", "vehicle_code": "MH01AA0003", "vehicle_type_id": w.lk["vehicle_type"]["Sedan"], "model": "M", "capacity": 2})
    w.client.patch(f"/api/drivers/{w.d1['id']}/status", headers=w.h["admin_a"], json={"status": "inactive"})
    today = datetime.now(IST).date()
    qs = f"range=custom&date_from={today - timedelta(days=1)}&date_to={today + timedelta(days=2)}"
    items = get(w, "/dashboard/exceptions", qs=qs).json()["items"]
    got = {(i["reason"], i["trip_id"]) for i in items}
    assert ("not_started", late["id"]) in got
    assert ("awaiting_acceptance", soon["id"]) in got
    assert ("capacity_conflict", big["id"]) in got
    assert ("driver_inactive", big["id"]) in got
    assert all(i["message"] and i["code"] for i in items)
    assert get(w, "/dashboard/exceptions", who="admin_b", qs=qs).json()["items"] == []


# ---------------------------------------------------------------- reports
def test_report_catalog_is_role_aware(w):
    keys = lambda who: {r["key"] for r in w.client.get("/api/reports", headers=w.h[who]).json()["items"]}  # noqa: E731
    assert "vendors" in keys("root") and "vendors" not in keys("admin_a") and "trips" in keys("oper_a")
    assert w.client.get("/api/reports/vendors?" + DAY, headers=w.h["admin_a"]).status_code == 403
    assert w.client.get("/api/reports/nope?" + DAY, headers=w.h["admin_a"]).status_code == 404


def test_trip_reports(busy):
    w = busy
    r = get(w, "/reports/trips").json()
    assert [c["label"] for c in r["columns"]][:3] == ["Trip ID", "Date", "Start"]
    assert len(r["rows"]) == 4 and r["summary"]["Trips"] == 4 and r["summary"]["Cancelled"] == 1
    first = r["rows"][0]
    assert first["date"] == "2030-01-07" and first["start"] == "14:30" and first["customer"] == "Acme"
    done = get(w, "/reports/completed-trips").json()
    assert [x["status"] for x in done["rows"]] == ["Completed"] and done["rows"][0]["escort"] == "Yes"
    canc = get(w, "/reports/cancelled-trips").json()
    assert canc["rows"][0]["reason"] == "Employee on leave" and canc["rows"][0]["cancelled_by"]


def test_utilization_and_other_reports(busy):
    w = busy
    drivers = get(w, "/reports/drivers").json()
    assert {r["name"]: r["trips"] for r in drivers["rows"]} == {"L1 D": 2, "L2 D": 1}
    vehicles = get(w, "/reports/vehicles").json()
    assert {r["vehicle_number"]: r["trips"] for r in vehicles["rows"]}["MH01AA0006"] == 1
    cap = get(w, "/reports/capacity").json()
    esc = next(r for r in cap["rows"] if r["escort"] == "Yes")
    assert (esc["capacity"], esc["passengers"], esc["required"], esc["free"], esc["util"]) == (4, 2, 3, 1, 75.0)
    res = get(w, "/reports/resources").json()
    assert {r["kind"] for r in res["rows"]} == {"Driver", "Vehicle"} and len(res["rows"]) == 5
    cust = get(w, "/reports/customers").json()
    assert cust["rows"] == [{"name": "Acme", "trips": 3, "completed": 1, "cancelled": 1, "passengers": 4}]
    assert get(w, "/reports/vendors", who="root").json()["rows"][0]["name"] == "Alpha"
    n = get(w, "/reports/notifications").json()
    assert n["rows"][0]["total"] == n["summary"]["Messages"] and n["rows"][0]["failed"] == 0


def test_reports_are_scoped_and_role_checked(busy):
    w = busy
    assert get(w, "/reports/trips", who="admin_b").json()["rows"] == []
    assert get(w, "/reports/drivers", who="admin_b").json()["rows"] == []
    assert get(w, "/reports/trips", who=w.dh1).status_code == 403
    sneaky = get(w, "/reports/trips", who="admin_b", qs=DAY + f"&vendor_id={w.world['va'].id}")
    assert sneaky.json()["rows"] == []


def test_xlsx_export(busy, db):
    w = busy
    r = get(w, "/reports/trips", qs=DAY + "&format=xlsx")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert 'filename="yaan-trips-' in r.headers["content-disposition"] and r.headers["content-disposition"].endswith('.xlsx"')
    ws = load_workbook(BytesIO(r.content)).active
    cells = [[c.value for c in row] for row in ws.iter_rows()]
    header_idx = next(i for i, row in enumerate(cells) if row[0] == "Trip ID")
    assert cells[0][0] == "YAAN — Trip summary" and "Period: 07 Jan 2030" in cells[1][0]
    body = cells[header_idx + 1:]
    assert len(body) == 4 and body[0][0].startswith("TRP-") and body[0][4] == "Acme"
    assert "report.exported" in set(db.scalars(select(AuditLog.action)))
    assert get(w, "/reports/trips", who="admin_b", qs=DAY + "&format=xlsx").status_code == 200   # empty but valid
    assert get(w, "/reports/trips", qs=DAY + "&format=pdf").status_code == 422


def test_xlsx_does_not_execute_formulas():
    from app.api.routes.reports import to_xlsx
    evil = '=HYPERLINK("http://evil","click")'
    rep = {"title": "t", "summary": {}, "columns": [{"key": "a", "label": "A", "width": 10}], "rows": [{"a": evil}, {"a": "ok"}]}
    ws = load_workbook(BytesIO(to_xlsx(rep, "p"))).active
    cell = ws["A5"]                       # title, period, blank summary, header row 4, first data row 5
    assert cell.value == evil and cell.data_type == "s"     # stored as text, never evaluated
    assert ws["A6"].value == "ok"
