from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.models import LookupValue, Role, Trip
from tests.conftest import CONTACT, GEO, PASSWORD, auth, employee_extras, login, make_user, verify_all_otps

BASE = datetime(2030, 1, 7, 9, 0, tzinfo=timezone.utc)  # a Monday, 09:00 UTC


def iso(minutes: int = 0) -> str:
    return (BASE + timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def lk(db):
    out: dict[str, dict[str, int]] = {}
    for r in db.scalars(select(LookupValue)):
        out.setdefault(r.category, {})[r.label] = r.id
    return out


class W:  # test world for vendor A (+ a second vendor's admin)
    pass


@pytest.fixture
def w(client, world, db, lk):
    x = W()
    x.client, x.lk, x.world = client, lk, world
    op = make_user(db, "oper_a", Role.OPERATOR, world["va"].id)
    x.h = {n: auth(client, n) for n in ("root", "admin_a", "admin_b", "oper_a")}
    a = x.h["admin_a"]

    def post(path, body, h=a):
        r = client.post(path, headers=h, json=body)
        assert r.status_code == 201, r.text
        return r.json()

    x.post = post
    x.customer = post("/api/customers", {"code": "C1", "name": "Acme", **GEO, **CONTACT})
    op.customer_id = x.customer["id"]  # an Operator works for one customer
    db.commit()
    x.site = post("/api/sites", {"customer_id": x.customer["id"], "name": "HQ", "address": "1 Main St"})
    emp = lambda code, g: post("/api/employees", dict(  # noqa: E731
        customer_id=x.customer["id"], employee_code=code, first_name=code, last_name="E", mobile="9876543210", gender=g, **GEO, **employee_extras(client, a, x.customer["id"], code)))
    x.f1, x.f2 = emp("F1", "female"), emp("F2", "female")
    x.m1, x.m2, x.m3 = emp("M1", "male"), emp("M2", "male"), emp("M3", "male")
    drv = lambda lic: post("/api/drivers", dict(  # noqa: E731
        first_name=lic, last_name="D", contact_number="9000000001", gender="male",
        license_type_id=lk["license_type"]["LMV"], license_number=lic, email="d@example.com", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road"))
    x.d1, x.d2 = drv("L1"), drv("L2")
    veh = lambda num, cap: post("/api/vehicles", dict(  # noqa: E731
        vehicle_number=num, vehicle_code=num, vehicle_type_id=lk["vehicle_type"]["Sedan"], model="M", capacity=cap))
    x.v3, x.v4, x.v6 = veh("MH01AA0003", 3), veh("MH01AA0004", 4), veh("MH01AA0006", 6)
    x.pickup = lk["trip_type"]["Pickup"]
    return x


def trip_body(w, emps=None, driver=None, vehicle=None, start=0, end=60, **kw):
    body = dict(customer_id=w.customer["id"], site_id=w.site["id"], trip_type_id=w.pickup,
                scheduled_start=iso(start), scheduled_end=iso(end), pickup_address="Home", drop_address="Office",
                employee_ids=[e["id"] for e in (emps or [w.m1])], driver_id=(driver or w.d1)["id"],
                vehicle_id=(vehicle or w.v4)["id"])
    body.update(kw)
    return body


def create(w, h=None, **kw):
    return w.client.post("/api/trips", headers=h or w.h["admin_a"], json=trip_body(w, **kw))


def err_codes(r):
    return {d.get("code") for d in r.json()["detail"] if isinstance(d, dict)}


# ---------------------------------------------------------------- creation
def test_operator_creates_trip(w, db):
    r = create(w, emps=[w.m1, w.m2])
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "assigned" and t["code"] == f"TRP-{t['id']:06d}"
    assert t["passenger_count"] == 2 and t["escort_required"] is False and t["required_capacity"] == 2
    assert t["driver_name"] and t["vehicle_number"] == "MH01AA0004"
    detail = w.client.get(f"/api/trips/{t['id']}", headers=w.h["admin_a"]).json()
    assert [p["name"] for p in detail["passengers"]] == ["M1 E", "M2 E"]
    assert detail["history"][0]["to"] == "assigned"


def test_end_time_is_required_and_validated(w):
    body = trip_body(w)
    del body["scheduled_end"]
    assert w.client.post("/api/trips", headers=w.h["admin_a"], json=body).status_code == 422
    assert create(w, start=60, end=60).status_code == 422
    assert create(w, start=60, end=30).status_code == 422
    naive = trip_body(w, scheduled_start="2030-01-07T09:00:00")
    assert w.client.post("/api/trips", headers=w.h["admin_a"], json=naive).status_code == 422


def test_required_fields(w):
    for key in ("driver_id", "vehicle_id", "customer_id"):
        body = trip_body(w)
        body[key] = None
        r = w.client.post("/api/trips", headers=w.h["admin_a"], json=body)
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == key
    assert create(w, employee_ids=[]).status_code == 422


# ---------------------------------------------------------------- 30 minute buffer
def test_driver_buffer_boundaries(w):
    assert create(w, start=0, end=60).status_code == 201          # 09:00-10:00
    # a different vehicle each time so only the DRIVER can conflict
    r = create(w, vehicle=w.v6, start=89, end=150)                  # starts 10:29 -> too close
    assert r.status_code == 409 and "driver_conflict" in err_codes(r)
    assert create(w, vehicle=w.v6, start=90, end=150).status_code == 201   # exactly 10:30 -> allowed
    # before the existing trip: needs 30 min gap too
    assert create(w, vehicle=w.v3, start=-90, end=-29).status_code == 409   # ends 08:31
    assert create(w, vehicle=w.v3, start=-90, end=-30).status_code == 201   # ends 08:30 -> allowed


def test_vehicle_buffer_applies_the_same_way(w):
    assert create(w, start=0, end=60).status_code == 201
    r = create(w, driver=w.d2, start=89, end=150)
    assert r.status_code == 409 and "vehicle_conflict" in err_codes(r)
    assert create(w, driver=w.d2, start=90, end=150).status_code == 201


def test_overlap_and_containment_conflict(w):
    assert create(w, start=0, end=120).status_code == 201
    assert create(w, vehicle=w.v6, start=30, end=60).status_code == 409   # fully inside
    assert create(w, vehicle=w.v6, start=-30, end=200).status_code == 409  # surrounds it


# ---------------------------------------------------------------- capacity / escort
def test_capacity_and_escort_seat(w):
    three_men = [w.m1, w.m2, w.m3]
    ok = create(w, emps=three_men, vehicle=w.v3)               # needs 3, seats 3
    assert ok.status_code == 201 and ok.json()["escort_required"] is False

    with_woman = [w.m1, w.m2, w.f1]                              # 3 + escort seat = 4
    r = create(w, emps=with_woman, vehicle=w.v3, driver=w.d2, start=300, end=360)
    assert r.status_code == 409 and "capacity_too_low" in err_codes(r)
    ok2 = create(w, emps=with_woman, vehicle=w.v4, driver=w.d2, start=300, end=360)
    assert ok2.status_code == 201
    assert ok2.json()["escort_required"] is True and ok2.json()["required_capacity"] == 4
    assert ok2.json()["passenger_count"] == 3  # escort seat is not counted as a passenger

    two_women = create(w, emps=[w.f1, w.f2], vehicle=w.v4, driver=w.d1, start=600, end=660)
    assert two_women.json()["required_capacity"] == 3  # escort seat is 1 regardless of how many women


def test_inactive_resources_cannot_be_assigned(w):
    a = w.h["admin_a"]
    w.client.patch(f"/api/drivers/{w.d1['id']}/status", headers=a, json={"status": "inactive"})
    w.client.patch(f"/api/vehicles/{w.v4['id']}/status", headers=a, json={"status": "inactive"})
    r = create(w)
    assert r.status_code == 409 and "driver_inactive" in err_codes(r)
    r = create(w, driver=w.d2)
    assert "vehicle_inactive" in err_codes(r)


def test_passenger_validation(w, db):
    other = w.post("/api/customers", {"code": "C2", "name": "Other", **GEO, **CONTACT})
    stranger = w.post("/api/employees", dict(customer_id=other["id"], employee_code="X", first_name="X", last_name="Y",
                                             mobile="9876543210", gender="male", **GEO, **employee_extras(w.client, w.h["admin_a"], other["id"], "X")))
    r = create(w, emps=[stranger])
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "employee_ids"
    w.client.patch(f"/api/employees/{w.m1['id']}/status", headers=w.h["admin_a"], json={"status": "inactive"})
    assert create(w, emps=[w.m1]).status_code == 422
    assert create(w, employee_ids=[w.m2["id"], w.m2["id"]]).status_code == 422


# ---------------------------------------------------------------- availability endpoints
def test_availability_lists_reasons(w):
    create(w, start=0, end=60)
    q = f"start={iso(70).replace('+', '%2B')}&end={iso(120).replace('+', '%2B')}"
    d = w.client.get(f"/api/drivers/availability?{q}", headers=w.h["admin_a"]).json()["items"]
    by = {x["name"]: x for x in d}
    assert by["L1 D"]["available"] is False and by["L1 D"]["reasons"][0]["code"] == "driver_conflict"
    assert by["L2 D"]["available"] is True

    ids = f"{w.m1['id']},{w.f1['id']},{w.m2['id']}"
    v = w.client.get(f"/api/vehicles/availability?{q}&employee_ids={ids}", headers=w.h["admin_a"]).json()
    assert v["required_capacity"] == 4 and v["escort_required"] is True and v["passenger_count"] == 3
    by = {x["vehicle_number"]: x for x in v["items"]}
    assert [r["code"] for r in by["MH01AA0003"]["reasons"]] == ["capacity_too_low"]
    assert by["MH01AA0004"]["available"] is False and "vehicle_conflict" in {r["code"] for r in by["MH01AA0004"]["reasons"]}
    assert by["MH01AA0006"]["available"] is True


def test_availability_ignores_cancelled_and_supports_exclude(w):
    t = create(w, start=0, end=60).json()
    q = f"start={iso(0).replace('+', '%2B')}&end={iso(60).replace('+', '%2B')}"
    mine = w.client.get(f"/api/drivers/availability?{q}&exclude_trip_id={t['id']}", headers=w.h["admin_a"]).json()["items"]
    assert all(x["available"] for x in mine)  # editing the trip itself doesn't conflict with itself
    w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "not needed"})
    free = w.client.get(f"/api/drivers/availability?{q}", headers=w.h["admin_a"]).json()["items"]
    assert all(x["available"] for x in free)


def test_availability_is_vendor_scoped(w):
    q = f"start={iso(0).replace('+', '%2B')}&end={iso(60).replace('+', '%2B')}"
    assert w.client.get(f"/api/drivers/availability?{q}", headers=w.h["admin_b"]).json()["items"] == []
    assert w.client.get(f"/api/drivers/availability?{q}&vendor_id={w.world['va'].id}", headers=w.h["root"]).status_code == 200
    assert w.client.get(f"/api/drivers/availability?{q}", headers=w.h["root"]).status_code == 422  # super admin must pick


# ---------------------------------------------------------------- cancel
def test_cancel_releases_resources_and_keeps_history(w):
    t = create(w, start=0, end=60).json()
    assert create(w, start=0, end=60).status_code == 409
    no_reason = w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": ""})
    assert no_reason.status_code == 422
    r = w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "Employee on leave"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert r.json()["cancelled_by"] and r.json()["cancellation_reason"] == "Employee on leave" and r.json()["cancelled_at"]
    assert create(w, start=0, end=60).status_code == 201  # same driver+vehicle+slot is free again
    listed = w.client.get("/api/trips?view=cancelled", headers=w.h["admin_a"]).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == t["id"]  # never hard-deleted
    again = w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "again"})
    assert again.status_code == 409


# ---------------------------------------------------------------- edit / reassign
def test_edit_revalidates_availability(w):
    t1 = create(w, start=0, end=60).json()
    t2 = create(w, vehicle=w.v6, start=120, end=180).json()   # same driver, later
    put = lambda tid, **kw: w.client.put(f"/api/trips/{tid}", headers=w.h["admin_a"], json=trip_body(w, **kw))  # noqa: E731
    # moving t2 to touch t1's buffer fails, moving it to 10:30 works
    assert put(t2["id"], vehicle=w.v6, start=60, end=100).status_code == 409
    ok = put(t2["id"], vehicle=w.v6, start=90, end=150)
    assert ok.status_code == 200 and ok.json()["scheduled_start"].startswith("2030-01-07T10:30")
    # a trip never conflicts with itself
    assert put(t1["id"], start=0, end=45).status_code == 200
    # adding a woman needs one extra seat: v3 has 3 seats, 3 passengers + escort = 4
    t3 = create(w, emps=[w.m1, w.m2, w.m3], vehicle=w.v3, driver=w.d2, start=500, end=560).json()
    r = put(t3["id"], emps=[w.m1, w.m2, w.f1], vehicle=w.v3, driver=w.d2, start=500, end=560)
    assert r.status_code == 409 and "capacity_too_low" in err_codes(r)


def test_reassign_checks_everything_and_resets_acceptance(w, db):
    t = create(w, start=0, end=60).json()
    create(w, driver=w.d2, vehicle=w.v6, start=0, end=60)           # d2 + v6 busy
    assign = lambda **kw: w.client.post(f"/api/trips/{t['id']}/assign", headers=w.h["admin_a"], json=kw)  # noqa: E731
    assert "driver_conflict" in err_codes(assign(driver_id=w.d2["id"]))
    assert "vehicle_conflict" in err_codes(assign(vehicle_id=w.v6["id"]))
    assert assign().status_code == 422

    drv = make_user(db, "drv1", Role.DRIVER, w.world["va"].id, driver_id=w.d1["id"])
    dh = auth(w.client, "drv1")
    assert w.client.post(f"/api/trips/{t['id']}/status", headers=dh, json={"status": "accepted"}).status_code == 200
    d3 = w.post("/api/drivers", dict(first_name="L3", last_name="D", contact_number="9000000003", gender="male",
                                      license_type_id=w.lk["license_type"]["LMV"], license_number="L3", email="d@example.com", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road"))
    r = assign(driver_id=d3["id"])
    assert r.status_code == 200 and r.json()["driver_id"] == d3["id"]
    assert r.json()["status"] == "assigned"                                  # new driver hasn't accepted
    detail = w.client.get(f"/api/trips/{t['id']}", headers=w.h["admin_a"]).json()
    assert [h["to"] for h in detail["history"]] == ["assigned", "accepted", "assigned"]
    # old driver is free again, so another trip fits their slot
    assert create(w, driver=w.d1, vehicle=w.v3, start=0, end=60).status_code == 201


def test_edit_restrictions_by_status(w, db):
    t = create(w).json()
    make_user(db, "drv1", Role.DRIVER, w.world["va"].id, driver_id=w.d1["id"])
    dh = auth(w.client, "drv1")
    put = lambda **kw: w.client.put(f"/api/trips/{t['id']}", headers=w.h["admin_a"], json=trip_body(w, **kw))  # noqa: E731
    for s in ("accepted", "started"):
        w.client.post(f"/api/trips/{t['id']}/status", headers=dh, json={"status": s})
    assert put(start=10, end=70).status_code == 409                                   # started: operational change
    notes = put(special_instructions="Call on arrival")                                 # started: notes ok
    assert notes.status_code == 200 and notes.json()["special_instructions"] == "Call on arrival"
    assert w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "late"}).status_code == 409
    verify_all_otps(w.client, dh, t["id"])                                              # the trip can only end once everyone is dropped
    w.client.post(f"/api/trips/{t['id']}/status", headers=dh, json={"status": "completed"})
    assert put(special_instructions="x").status_code == 409                             # completed: frozen


# ---------------------------------------------------------------- driver workflow
@pytest.fixture
def driver_world(w, db):
    make_user(db, "drv1", Role.DRIVER, w.world["va"].id, driver_id=w.d1["id"])
    make_user(db, "drv2", Role.DRIVER, w.world["va"].id, driver_id=w.d2["id"])
    w.dh1, w.dh2 = auth(w.client, "drv1"), auth(w.client, "drv2")
    return w


def test_driver_lifecycle_and_audit(driver_world, db):
    w = driver_world
    t = create(w).json()
    st = lambda s, h=None: w.client.post(f"/api/trips/{t['id']}/status", headers=h or w.dh1, json={"status": s})  # noqa: E731
    assert st("started").status_code == 409            # cannot skip Accepted
    assert st("completed").status_code == 409
    r = st("accepted")
    assert r.status_code == 200 and r.json()["status"] == "accepted" and r.json()["accepted_at"]
    assert st("accepted").status_code == 409           # duplicate tap/retry
    assert st("started").json()["started_at"]
    assert st("started").status_code == 409
    blocked = st("completed")                          # cannot end the trip until every employee has been dropped
    assert blocked.status_code == 409 and blocked.json()["detail"][0]["code"] == "otp_pending"
    verify_all_otps(w.client, w.dh1, t["id"])
    assert st("completed").json()["status"] == "completed"
    assert st("accepted").status_code == 409           # terminal
    detail = w.client.get(f"/api/trips/{t['id']}", headers=w.h["admin_a"]).json()
    assert [h["to"] for h in detail["history"]] == ["assigned", "accepted", "started", "completed"]
    from app.models import AuditLog
    assert {"trip.accepted", "trip.started", "trip.completed"} <= set(db.scalars(select(AuditLog.action)))
    assert st("invalid").status_code == 422


def test_driver_only_sees_and_touches_own_trips(driver_world):
    w = driver_world
    mine = create(w).json()
    theirs = create(w, driver=w.d2, vehicle=w.v6).json()
    ids = [x["id"] for x in w.client.get("/api/trips", headers=w.dh1).json()["items"]]
    assert ids == [mine["id"]]
    assert w.client.get(f"/api/trips/{theirs['id']}", headers=w.dh1).status_code == 404
    assert w.client.post(f"/api/trips/{theirs['id']}/status", headers=w.dh1, json={"status": "accepted"}).status_code == 404
    # filters can't widen the scope
    assert w.client.get(f"/api/trips?driver_id={w.d2['id']}", headers=w.dh1).json()["total"] == 0
    # drivers see passenger names but not phone numbers
    p = w.client.get(f"/api/trips/{mine['id']}", headers=w.dh1).json()
    assert p["passengers"][0]["name"] and "mobile" not in p["passengers"][0] and p["driver_contact"] is None


def test_driver_cannot_manage_trips(driver_world):
    w = driver_world
    t = create(w).json()
    assert create(w, h=w.dh1, driver=w.d2).status_code == 403
    assert w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.dh1, json={"reason": "no"}).status_code == 403
    assert w.client.put(f"/api/trips/{t['id']}", headers=w.dh1, json=trip_body(w)).status_code == 403
    assert w.client.post(f"/api/trips/{t['id']}/assign", headers=w.dh1, json={"driver_id": w.d2["id"]}).status_code == 403
    assert w.client.get("/api/drivers/availability?start=x&end=y", headers=w.dh1).status_code == 403


def test_operators_cannot_use_driver_status_endpoint(w):
    t = create(w).json()
    r = w.client.post(f"/api/trips/{t['id']}/status", headers=w.h["admin_a"], json={"status": "accepted"})
    assert r.status_code == 403


# ---------------------------------------------------------------- isolation
def test_vendor_isolation_on_trips(w):
    t = create(w).json()
    b = w.h["admin_b"]
    assert w.client.get("/api/trips", headers=b).json()["total"] == 0
    assert w.client.get(f"/api/trips/{t['id']}", headers=b).status_code == 404
    assert w.client.put(f"/api/trips/{t['id']}", headers=b, json=trip_body(w)).status_code == 404
    assert w.client.post(f"/api/trips/{t['id']}/cancel", headers=b, json={"reason": "hax"}).status_code == 404
    assert w.client.post(f"/api/trips/{t['id']}/assign", headers=b, json={"driver_id": w.d2["id"]}).status_code == 404
    # vendor B cannot book vendor A's customer / resources
    assert create(w, h=b).status_code == 404
    assert w.client.get("/api/trips", headers=w.h["root"]).json()["total"] == 1


def test_cannot_mix_vendors_inside_a_trip(w):
    other = w.post("/api/drivers", dict(first_name="B", last_name="Driver", contact_number="9000000009", gender="male",
                                         license_type_id=w.lk["license_type"]["LMV"], license_number="B1", email="d@example.com", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road"), h=w.h["admin_b"])
    r = create(w, driver=other)
    assert r.status_code == 422 and "driver_invalid" in err_codes(r)


# ---------------------------------------------------------------- list filters
def test_list_views_and_filters(w, db):
    a = create(w, start=0, end=60).json()
    b = create(w, driver=w.d2, vehicle=w.v6, start=1440, end=1500).json()   # next day
    h = w.h["admin_a"]
    get = lambda qs: w.client.get(f"/api/trips?{qs}", headers=h).json()  # noqa: E731
    assert get("view=all")["total"] == 2
    assert get("view=assigned")["total"] == 2 and get("view=accepted")["total"] == 0
    assert get(f"driver_id={w.d2['id']}")["items"][0]["id"] == b["id"]
    assert get(f"vehicle_id={w.v4['id']}")["items"][0]["id"] == a["id"]
    assert get(f"employee_id={w.m1['id']}")["total"] == 2
    assert get("q=" + a["code"])["total"] == 1
    assert get("date_from=2030-01-08&date_to=2030-01-08")["total"] == 1
    assert get(f"customer_id={w.customer['id']}&status=assigned")["total"] == 2
    assert get("limit=1")["total"] == 2 and len(get("limit=1")["items"]) == 1


# ---------------------------------------------------------------- shifts / vendor deactivation
def test_shifts_defined_per_customer(w):
    a = w.h["admin_a"]
    s = w.post("/api/shifts", {"customer_id": w.customer["id"], "name": "Night", "start_time": "22:00", "end_time": "06:00"})
    assert s["start_time"].startswith("22:00") and s["end_time"].startswith("06:00")
    assert w.client.post("/api/shifts", headers=a, json={"customer_id": w.customer["id"], "name": "night", "start_time": "01:00", "end_time": "02:00"}).status_code == 422
    assert w.client.post("/api/shifts", headers=w.h["oper_a"], json={"customer_id": w.customer["id"], "name": "X", "start_time": "01:00", "end_time": "02:00"}).status_code == 403
    assert w.client.get("/api/shifts?q=Night", headers=w.h["oper_a"]).json()["total"] == 1
    assert w.client.get("/api/shifts", headers=w.h["admin_b"]).json()["total"] == 0
    # trip + employee may use it
    assert create(w, shift_id=s["id"]).json()["shift_name"] == "Night"
    # another customer's shift is rejected
    c2 = w.post("/api/customers", {"code": "C2", "name": "Other", **GEO, **CONTACT})
    s2 = w.post("/api/shifts", {"customer_id": c2["id"], "name": "Day", "start_time": "09:00", "end_time": "18:00"})
    assert create(w, shift_id=s2["id"], start=300, end=360).status_code == 422


def test_deactivated_vendor_is_locked_out(w):
    old = w.h["admin_a"]
    assert w.client.get("/api/trips", headers=old).status_code == 200
    r = w.client.patch(f"/api/vendors/{w.world['va'].id}/status", headers=w.h["root"], json={"status": "inactive"})
    assert r.status_code == 200
    assert w.client.get("/api/trips", headers=old).status_code == 401           # existing session dies
    blocked = login(w.client, "oper_a")
    assert blocked.status_code == 401 and "organisation" in blocked.json()["detail"].lower()
    w.client.patch(f"/api/vendors/{w.world['va'].id}/status", headers=w.h["root"], json={"status": "active"})
    assert login(w.client, "oper_a").status_code == 200


# ---------------------------------------------------------------- concurrency / DB backstop
def test_concurrent_bookings_only_one_wins(w):
    clients = [TestClient(app) for _ in range(6)]

    def go(c):
        r = c.post("/api/trips", headers=w.h["admin_a"], json=trip_body(w, start=0, end=60))
        return r.status_code

    with ThreadPoolExecutor(6) as ex:
        codes = list(ex.map(go, clients))
    assert sorted(codes).count(201) == 1 and codes.count(409) == 5, codes


def test_database_itself_rejects_double_booking(w, db):
    create(w, start=0, end=60)
    t = db.scalar(select(Trip))
    with pytest.raises(IntegrityError):
        db.execute(text(
            "insert into trips (vendor_id, customer_id, site_id, trip_type_id, scheduled_start, scheduled_end, block_end,"
            " pickup_address, drop_address, passenger_count, escort_required, required_capacity, driver_id, vehicle_id,"
            " status, created_by) select vendor_id, customer_id, site_id, trip_type_id, scheduled_start + interval '10 min',"
            " scheduled_end, block_end, 'a', 'b', 1, false, 1, driver_id, vehicle_id, 'assigned', created_by from trips"
            f" where id = {t.id}"))
        db.commit()
    db.rollback()


def test_route_and_live_location(driver_world, monkeypatch):
    monkeypatch.setattr("app.services.geocode.geocode", lambda *a, **k: None)  # no network in tests
    w = driver_world
    t = create(w).json()
    loc = lambda h, lat=18.5, lng=73.8: w.client.post(f"/api/trips/{t['id']}/location", headers=h, json={"latitude": lat, "longitude": lng})  # noqa: E731
    route = lambda h=None: w.client.get(f"/api/trips/{t['id']}/route", headers=h or w.h["admin_a"]).json()  # noqa: E731
    assert loc(w.dh1).status_code == 409                    # not started yet
    r = route()
    assert r["live"] is None and r["missing"] >= 0 and any(s["kind"] == "employee" for s in r["stops"])
    for s in ("accepted", "started"):
        w.client.post(f"/api/trips/{t['id']}/status", headers=w.dh1, json={"status": s})
    assert loc(w.dh1).status_code == 204
    assert loc(w.dh2).status_code == 404                    # another driver's trip
    assert loc(w.h["admin_a"]).status_code == 403           # only drivers report position
    assert loc(w.dh1, lat=200).status_code == 422
    assert route()["live"]["latitude"] == 18.5
    assert w.client.get(f"/api/trips/{t['id']}/route", headers=w.h["admin_b"]).status_code == 404  # vendor isolation


def test_trip_cannot_be_booked_in_the_past(w):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    stamp = lambda d: d.isoformat()  # noqa: E731
    past = w.client.post("/api/trips", headers=w.h["admin_a"], json=trip_body(
        w, scheduled_start=stamp(now - timedelta(hours=2)), scheduled_end=stamp(now - timedelta(hours=1))))
    assert past.status_code == 422
    assert any("past" in str(d.get("msg", "")) for d in past.json()["detail"])
    # a request from an Operator is held to the same rule
    op = w.client.post("/api/trips", headers=w.h["oper_a"], json={k: v for k, v in trip_body(
        w, scheduled_start=stamp(now - timedelta(days=1)), scheduled_end=stamp(now - timedelta(days=1) + timedelta(hours=1))).items()
        if k not in ("driver_id", "vehicle_id")})
    assert op.status_code == 422 and any("past" in str(d.get("msg", "")) for d in op.json()["detail"]), op.text
    # a future start is fine
    ok = w.client.post("/api/trips", headers=w.h["admin_a"], json=trip_body(
        w, scheduled_start=stamp(now + timedelta(hours=3)), scheduled_end=stamp(now + timedelta(hours=4))))
    assert ok.status_code == 201, ok.text
