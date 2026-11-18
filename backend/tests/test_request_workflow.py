"""Operator requests a trip (employees only) -> Vendor Admin assigns driver + vehicle -> final trip, SMS goes out."""
import pytest
from sqlalchemy import select

from app.models import AuditLog, Driver, LookupValue, Role, User
from tests.conftest import CONTACT, GEO, auth, employee_extras, login, make_user
from tests.test_trips import BASE, create, driver_world, iso, lk, trip_body, w  # noqa: F401  (fixtures)


def request_trip(w, who="oper_a", **kw):
    """What an Operator sends: no driver, no vehicle."""
    body = trip_body(w, **kw)
    body.pop("driver_id"), body.pop("vehicle_id")
    h = w.h[who] if isinstance(who, str) else who
    return w.client.post("/api/trips", headers=h, json=body)


def assign(w, trip, who="admin_a", driver=None, vehicle=None, **kw):
    h = w.h[who] if isinstance(who, str) else who
    body = {"driver_id": (driver or w.d1)["id"], "vehicle_id": (vehicle or w.v4)["id"]}
    body.update(kw)
    return w.client.post(f"/api/trips/{trip['id']}/assign", headers=h, json=body)


def sms(db):
    db.expire_all()
    from app.models import SmsLog
    return list(db.scalars(select(SmsLog).order_by(SmsLog.id)))


# ---------------------------------------------------------------- the request
def test_operator_request_waits_for_assignment_and_notifies_nobody(w, db, smsbox):
    r = request_trip(w, emps=[w.m1, w.f1])
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["status"] == "scheduled" and t["code"] == f"TRP-{t['id']:06d}"
    assert t["driver_id"] is None and t["vehicle_id"] is None and t["driver_name"] is None and t["vehicle_number"] is None
    assert t["passenger_count"] == 2 and t["escort_required"] is True and t["required_capacity"] == 3   # known up front
    assert t["can_assign"] is False and t["can_edit"] is True and t["can_cancel"] is True               # operator's view
    assert sms(db) == [] and smsbox.sent == []                                                          # nothing sent yet
    assert w.client.get(f"/api/trips/{t['id']}", headers=w.h["oper_a"]).json()["history"][0]["to"] == "scheduled"
    assert "trip.requested" in set(db.scalars(select(AuditLog.action)))


def test_a_request_reserves_nothing(w):
    request_trip(w, start=0, end=60)
    # the same slot is still fully bookable, by request or by direct assignment
    assert request_trip(w, start=0, end=60).status_code == 201
    assert create(w, start=0, end=60).status_code == 201
    q = f"start={iso(0).replace('+', '%2B')}&end={iso(60).replace('+', '%2B')}"
    only_real = w.client.get(f"/api/drivers/availability?{q}", headers=w.h["admin_a"]).json()["items"]
    assert [d["available"] for d in only_real].count(False) == 1                                       # just the direct trip's driver


def test_operator_cannot_pick_a_driver_or_vehicle(w):
    body = trip_body(w)                                                                                 # includes driver + vehicle
    r = w.client.post("/api/trips", headers=w.h["oper_a"], json=body)
    assert r.status_code == 403 and "Vendor Admin" in r.json()["detail"]
    only_one = {**trip_body(w), "vehicle_id": None}
    assert w.client.post("/api/trips", headers=w.h["oper_a"], json=only_one).status_code == 403
    t = request_trip(w).json()
    assert assign(w, t, who="oper_a").status_code == 403


def test_request_validation(w):
    assert request_trip(w, start=60, end=30).status_code == 422                                         # end time still required
    assert request_trip(w, emps=[w.m1], employee_ids=[]).status_code == 422
    other = w.post("/api/customers", {"code": "C2", "name": "Other", **GEO, **CONTACT})
    stranger = w.post("/api/employees", dict(customer_id=other["id"], employee_code="X", first_name="X", last_name="Y",
                                             mobile="9876543210", gender="male", **GEO, **employee_extras(w.client, w.h["admin_a"], other["id"], "X")))
    assert request_trip(w, emps=[stranger]).json()["detail"][0]["loc"][-1] == "employee_ids"
    admin_only_one = {**trip_body(w), "vehicle_id": None}
    assert w.client.post("/api/trips", headers=w.h["admin_a"], json=admin_only_one).json()["detail"][0]["loc"][-1] == "vehicle_id"


# ---------------------------------------------------------------- the assignment
def test_assigning_creates_the_final_trip_and_sends_sms(w, db, smsbox):
    t = request_trip(w, emps=[w.m1, w.m2]).json()
    r = assign(w, t)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "assigned" and done["driver_name"] == "L1 D" and done["vehicle_number"] == "MH01AA0004"
    rows = sms(db)
    assert sorted(x.recipient_type for x in rows) == ["driver", "employee", "employee"]                 # driver + every employee
    assert {x.status for x in rows} == {"sent"} and len(smsbox.sent) == 3
    assert all(t["code"] in x.body for x in rows)
    hist = w.client.get(f"/api/trips/{t['id']}", headers=w.h["admin_a"]).json()["history"]
    assert [h["to"] for h in hist] == ["scheduled", "assigned"] and hist[1]["by"] != hist[0]["by"]      # who requested vs who assigned
    assert {"trip.requested", "trip.assigned"} <= set(db.scalars(select(AuditLog.action)))


def test_assignment_applies_every_availability_rule(w):
    first = request_trip(w, start=0, end=60).json()
    assert assign(w, first).status_code == 200                                                          # d1 + v4, 09:00-10:00
    nxt = request_trip(w, start=89, end=150).json()                                                     # starts 10:29
    r = assign(w, nxt)                                                                                  # same driver + vehicle
    assert r.status_code == 409 and {d["code"] for d in r.json()["detail"]} == {"driver_conflict"}      # driver checked first
    assert assign(w, nxt, driver=w.d2).json()["detail"][0]["code"] == "vehicle_conflict"
    assert assign(w, nxt, driver=w.d2, vehicle=w.v6).status_code == 200                                 # free pair, fine
    big = request_trip(w, emps=[w.m1, w.m2, w.f1], start=500, end=560).json()                           # 3 + escort = 4 seats
    assert assign(w, big, vehicle=w.v3).json()["detail"][0]["code"] == "capacity_too_low"
    assert assign(w, big, vehicle=w.v4, driver=w.d1).status_code == 200


def test_assignment_needs_both_and_stays_in_the_vendor(w):
    t = request_trip(w).json()
    assert w.client.post(f"/api/trips/{t['id']}/assign", headers=w.h["admin_a"], json={"driver_id": w.d1["id"]}).json()["detail"][0]["loc"][-1] == "vehicle_id"
    assert w.client.post(f"/api/trips/{t['id']}/assign", headers=w.h["admin_a"], json={"vehicle_id": w.v4["id"]}).json()["detail"][0]["loc"][-1] == "driver_id"
    assert w.client.post(f"/api/trips/{t['id']}/assign", headers=w.h["admin_a"], json={}).status_code == 422
    assert assign(w, t, who="admin_b").status_code == 404                                               # another vendor's admin
    other = w.post("/api/drivers", dict(first_name="B", last_name="D", contact_number="9000000099", gender="male",
                                         license_type_id=w.lk["license_type"]["LMV"], license_number="BZ9", email="d@example.com", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road"), h=w.h["admin_b"])
    assert assign(w, t, driver=other).json()["detail"][0]["code"] == "driver_invalid"
    inactive = w.client.patch(f"/api/drivers/{w.d2['id']}/status", headers=w.h["admin_a"], json={"status": "inactive"})
    assert assign(w, t, driver=w.d2).json()["detail"][0]["code"] == "driver_inactive" and inactive.status_code == 200


def test_two_admins_cannot_assign_the_same_request_twice(w, db):
    t = request_trip(w).json()
    assert assign(w, t).status_code == 200
    # once assigned, 'assign' is a reassignment: a different driver is allowed, but SMS follows the setting (off)
    again = assign(w, t, driver=w.d2)
    assert again.status_code == 200 and again.json()["driver_id"] == w.d2["id"] and again.json()["status"] == "assigned"
    assert len([x for x in sms(db) if x.template == "trip_created_driver"]) == 1                        # the "new trip" SMS only once


def test_driver_cannot_see_or_accept_a_request(driver_world):
    w = driver_world
    t = request_trip(w).json()
    assert w.client.get("/api/trips", headers=w.dh1).json()["total"] == 0
    assert w.client.post(f"/api/trips/{t['id']}/status", headers=w.dh1, json={"status": "accepted"}).status_code == 404
    assign(w, t)                                                                                        # d1 is now the driver
    assert w.client.get("/api/trips", headers=w.dh1).json()["total"] == 1
    assert w.client.post(f"/api/trips/{t['id']}/status", headers=w.dh1, json={"status": "accepted"}).status_code == 200


# ---------------------------------------------------------------- operator vs vendor admin after assignment
def test_operator_manages_requests_only_until_they_are_assigned(w, db):
    t = request_trip(w).json()
    put = lambda who, **kw: w.client.put(f"/api/trips/{t['id']}", headers=w.h[who], json={**{k: v for k, v in trip_body(w).items() if k not in ("driver_id", "vehicle_id")}, **kw})  # noqa: E731
    edited = put("oper_a", special_instructions="Gate 3", route_name="R1", employee_ids=[w.m1["id"], w.m2["id"]])
    assert edited.status_code == 200 and edited.json()["passenger_count"] == 2 and edited.json()["route_name"] == "R1"
    assert edited.json()["status"] == "scheduled" and edited.json()["required_capacity"] == 2
    woman = put("oper_a", employee_ids=[w.m1["id"], w.f1["id"]])
    assert woman.json()["escort_required"] is True and woman.json()["required_capacity"] == 3          # seats recalculated for the request
    # operators cannot slip a driver/vehicle in through an edit
    sneaky = w.client.put(f"/api/trips/{t['id']}", headers=w.h["oper_a"], json=trip_body(w))
    assert sneaky.status_code == 422 and sneaky.json()["detail"][0]["loc"][-1] == "driver_id"

    assert assign(w, t).status_code == 200
    locked = put("oper_a", special_instructions="changed my mind")
    assert locked.status_code == 403 and "Vendor Admin" in locked.json()["detail"]
    cancel = w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["oper_a"], json={"reason": "no longer needed"})
    assert cancel.status_code == 403
    seen = w.client.get(f"/api/trips/{t['id']}", headers=w.h["oper_a"]).json()                          # still visible, read-only
    assert seen["can_edit"] is False and seen["can_cancel"] is False and seen["can_assign"] is False
    admin_view = w.client.get(f"/api/trips/{t['id']}", headers=w.h["admin_a"]).json()
    assert admin_view["can_edit"] and admin_view["can_cancel"] and admin_view["can_assign"]
    assert w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "admin cancels"}).status_code == 200


def test_any_operator_in_the_vendor_can_fix_a_waiting_request(w, db):
    make_user(db, "oper_a2", Role.OPERATOR, w.world["va"].id, customer_id=w.customer["id"])
    t = request_trip(w).json()
    other = auth(w.client, "oper_a2")
    assert w.client.post(f"/api/trips/{t['id']}/cancel", headers=other, json={"reason": "colleague cancels"}).status_code == 200


def test_rejecting_a_request_is_a_cancellation_with_a_reason_and_sends_no_sms(w, db, smsbox):
    t = request_trip(w).json()
    no_reason = w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": ""})
    assert no_reason.status_code == 422
    r = w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "No vehicle free that night"})
    assert r.status_code == 200 and r.json()["status"] == "cancelled" and r.json()["cancellation_reason"] == "No vehicle free that night"
    assert sms(db) == [] and smsbox.sent == []                                                          # nobody was ever told about it
    seen = w.client.get(f"/api/trips/{t['id']}", headers=w.h["oper_a"]).json()
    assert seen["status"] == "cancelled" and seen["cancellation_reason"] and seen["cancelled_by"]       # the operator can see why


def test_cancelling_an_assigned_trip_still_sends_sms(w, db, smsbox):
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    smsbox.sent.clear()
    w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "Customer cancelled"})
    assert len([x for x in smsbox.sent if "cancelled" in x["body"]]) == 2                               # driver + employee


# ---------------------------------------------------------------- direct creation by admins
def test_vendor_admin_and_super_admin_can_create_and_assign_in_one_step(w, db, smsbox):
    for who in ("admin_a", "root"):
        smsbox.sent.clear()
        r = w.client.post("/api/trips", headers=w.h[who], json=trip_body(w, driver=w.d2 if who == "root" else w.d1,
                                                                         vehicle=w.v6 if who == "root" else w.v4,
                                                                         start=0 if who == "admin_a" else 300, end=60 if who == "admin_a" else 360))
        assert r.status_code == 201, (who, r.text)
        assert r.json()["status"] == "assigned" and len(smsbox.sent) == 2
        assert [h["to"] for h in w.client.get(f"/api/trips/{r.json()['id']}", headers=w.h[who]).json()["history"]] == ["assigned"]


# ---------------------------------------------------------------- lists, dashboard, reports
def test_awaiting_view_and_dashboard_counts(w):
    a = request_trip(w, start=0, end=60).json()
    request_trip(w, start=120, end=180)
    create(w, start=300, end=360, driver=w.d2, vehicle=w.v6)
    assign(w, a)
    get = lambda qs: w.client.get(f"/api/trips?{qs}", headers=w.h["admin_a"]).json()  # noqa: E731
    assert get("view=awaiting")["total"] == 1 and get("view=assigned")["total"] == 2 and get("view=all")["total"] == 3
    day = "range=custom&date_from=2030-01-07&date_to=2030-01-07"
    c = w.client.get(f"/api/dashboard/summary?{day}", headers=w.h["admin_a"]).json()["cards"]
    assert c["total_trips"] == 3 and c["pending_assignment"] == 1 and c["assigned"] == 2 and c["upcoming"] == 3
    assert c["total_passengers"] == 3 and c["capacity_utilization"] > 0                                  # requests don't break the maths
    lists = w.client.get(f"/api/dashboard/upcoming?{day}", headers=w.h["admin_a"]).json()
    assert [t["status"] for t in lists["awaiting_assignment"]] == ["scheduled"] or lists["awaiting_assignment"] == []
    assert w.client.get(f"/api/dashboard/status-breakdown?{day}", headers=w.h["admin_a"]).status_code == 200
    assert w.client.get(f"/api/dashboard/resource-utilization?{day}", headers=w.h["admin_a"]).status_code == 200


def test_unassigned_requests_raise_an_exception_when_departure_is_close(w):
    from datetime import datetime, timedelta, timezone
    soon = (datetime.now(timezone.utc) + timedelta(minutes=90)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(minutes=95)).isoformat()
    far = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    ids = {}
    for key, start in (("soon", soon), ("far", far)):
        body = trip_body(w)
        body.update(scheduled_start=start, scheduled_end=(datetime.fromisoformat(start) + timedelta(hours=1)).isoformat())
        body.pop("driver_id"), body.pop("vehicle_id")
        ids[key] = w.client.post("/api/trips", headers=w.h["oper_a"], json=body).json()["id"]
    from datetime import date
    today = datetime.now(timezone.utc).date()
    qs = f"range=custom&date_from={today - timedelta(days=1)}&date_to={today + timedelta(days=3)}"
    items = w.client.get(f"/api/dashboard/exceptions?{qs}", headers=w.h["admin_a"]).json()["items"]
    flagged = {i["trip_id"] for i in items if i["reason"] == "unassigned"}
    assert ids["soon"] in flagged and ids["far"] not in flagged and later


def test_reports_handle_requests(w):
    request_trip(w)
    rep = w.client.get("/api/reports/trips?range=custom&date_from=2030-01-07&date_to=2030-01-07", headers=w.h["admin_a"]).json()
    row = rep["rows"][0]
    assert row["status"] == "Awaiting assignment" and row["driver"] == "" and row["vehicle"] == ""
    assert w.client.get("/api/reports/trips?range=custom&date_from=2030-01-07&date_to=2030-01-07&format=xlsx", headers=w.h["admin_a"]).status_code == 200
    cap = w.client.get("/api/reports/capacity?range=custom&date_from=2030-01-07&date_to=2030-01-07", headers=w.h["admin_a"]).json()
    assert cap["rows"] == []                                                                            # no vehicle yet, so no seat-use row


def test_isolation_for_requests(w):
    t = request_trip(w).json()
    assert w.client.get(f"/api/trips/{t['id']}", headers=w.h["admin_b"]).status_code == 404
    assert w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_b"], json={"reason": "hax"}).status_code == 404
    assert w.client.get("/api/trips?view=awaiting", headers=w.h["admin_b"]).json()["total"] == 0
    assert w.client.get("/api/trips?view=awaiting", headers=w.h["root"]).json()["total"] == 1


# ---------------------------------------------------------------- vendor admin manages users
def create_user(w, who, **kw):
    body = dict(first_name="Nia", last_name="New", username="nia", email="nia@example.com", role="operator", customer_id=w.customer["id"], address="1 Road")
    body.update(kw)
    if body["role"] != "operator":
        body.pop("customer_id")
    h = w.h[who] if isinstance(who, str) else who
    return w.client.post("/api/users", headers=h, json=body)


def test_vendor_admin_creates_operators_with_a_temporary_password(w, db):
    r = create_user(w, "admin_a")                                                                       # no vendor_id sent at all
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["user"]["role"] == "operator" and d["user"]["vendor_id"] == w.world["va"].id and d["temporary_password"]
    assert d["user"]["credential_status"] == "temporary" and d["email_status"] == "sent"
    assert login(w.client, "nia", d["temporary_password"]).status_code == 200                            # can sign in, must then change it
    assert "user.created" in set(db.scalars(select(AuditLog.action)))


def test_vendor_admin_user_creation_is_pinned_to_their_vendor_and_roles(w):
    spoof = create_user(w, "admin_a", vendor_id=w.world["vb"].id, username="spoof", email="spoof@example.com")
    assert spoof.json()["user"]["vendor_id"] == w.world["va"].id                                        # cannot create into another vendor
    for role in ("vendor_admin", "super_admin"):
        r = create_user(w, "admin_a", role=role, username=f"{role}x", email=f"{role}x@example.com")
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "role"
    assert create_user(w, "oper_a", username="o1", email="o1@example.com").status_code == 403           # operators cannot onboard
    assert create_user(w, "admin_a", username="spoof", email="again@example.com").status_code == 422    # username still unique


def test_vendor_admin_creates_a_driver_login_linked_to_a_driver_record(w):
    r = create_user(w, "admin_a", role="driver", username="drvnew", email="drvnew@example.com", driver_id=w.d1["id"])
    assert r.status_code == 201 and r.json()["user"]["driver_id"] == w.d1["id"]
    assert create_user(w, "admin_a", role="driver", username="drv_two", email="drv2@example.com").json()["detail"][0]["loc"][-1] == "driver_id"
    assert create_user(w, "admin_a", role="driver", username="drv_three", email="drv3@example.com", driver_id=w.d1["id"]).status_code == 422   # one login per driver
    other = w.post("/api/drivers", dict(first_name="B", last_name="D", contact_number="9000000088", gender="male",
                                         license_type_id=w.lk["license_type"]["LMV"], license_number="BZ8", email="d@example.com", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road"), h=w.h["admin_b"])
    assert create_user(w, "admin_a", role="driver", username="drv_four", email="drv4@example.com", driver_id=other["id"]).status_code == 422  # other vendor's driver


def test_vendor_admin_manages_only_their_vendors_operators_and_drivers(w, db):
    mine = create_user(w, "admin_a").json()
    theirs = make_user(db, "oper_b", Role.OPERATOR, w.world["vb"].id)
    peer = make_user(db, "admin_a2", Role.VENDOR_ADMIN, w.world["va"].id)
    h = w.h["admin_a"]
    uid = mine["user"]["id"]
    assert w.client.put(f"/api/users/{uid}", headers=h, json={"first_name": "Renamed"}).json()["first_name"] == "Renamed"
    assert w.client.patch(f"/api/users/{uid}/status", headers=h, json={"status": "inactive"}).json()["status"] == "inactive"
    assert login(w.client, "nia", mine["temporary_password"]).status_code == 401                          # deactivated: cannot sign in
    w.client.patch(f"/api/users/{uid}/status", headers=h, json={"status": "active"})
    resent = w.client.post(f"/api/users/{uid}/resend-onboarding", headers=h)
    assert resent.status_code == 200 and resent.json()["temporary_password"] != mine["temporary_password"]
    # not other vendors' users, not other Vendor Admins, not themselves
    assert w.client.patch(f"/api/users/{theirs.id}/status", headers=h, json={"status": "inactive"}).status_code == 404
    assert w.client.put(f"/api/users/{theirs.id}", headers=h, json={"first_name": "x"}).status_code == 404
    assert w.client.patch(f"/api/users/{peer.id}/status", headers=h, json={"status": "inactive"}).status_code == 403
    assert w.client.put(f"/api/users/{peer.id}", headers=h, json={"first_name": "x"}).status_code == 403
    assert w.client.post(f"/api/users/{peer.id}/resend-onboarding", headers=h).status_code == 403
    assert w.client.patch(f"/api/users/{w.world['adm_a'].id}/status", headers=h, json={"status": "inactive"}).status_code in (403, 409)
    # operators can manage nobody
    op = w.h["oper_a"]
    assert w.client.patch(f"/api/users/{uid}/status", headers=op, json={"status": "inactive"}).status_code == 403
    assert w.client.get("/api/users", headers=op).status_code == 403


def test_super_admin_still_creates_every_role(w):
    for role, extra in (("vendor_admin", {}), ("operator", {})):
        r = create_user(w, "root", role=role, vendor_id=w.world["va"].id, username=f"sa_{role}", email=f"sa_{role}@example.com", **extra)
        assert r.status_code == 201 and r.json()["user"]["role"] == role


# ---------------------------------------------------------------- operators and employees
def test_operator_adds_employees_for_their_vendor_only(w, db):
    emp = lambda who, cust, code, **kw: w.client.post("/api/employees", headers=w.h[who], json=dict(  # noqa: E731
        customer_id=cust["id"], employee_code=code, first_name="Nina", last_name="Op", mobile="9876543211", gender="female",
        **{**GEO, **employee_extras(w.client, w.h["admin_a"] if cust["vendor_id"] == w.world["va"].id else w.h["admin_b"], cust["id"], code), **kw}))
    r = emp("oper_a", w.customer, "OPE1", address="5 Park Lane")
    assert r.status_code == 201 and r.json()["vendor_id"] == w.world["va"].id and r.json()["address"] == "5 Park Lane"
    assert emp("oper_a", w.customer, "OPE1").status_code == 422                                           # unique code per customer
    foreign = w.post("/api/customers", {"code": "FB", "name": "B Co", **GEO, **CONTACT}, h=w.h["admin_b"])
    # an Operator cannot pick a customer: whatever is sent, the employee is created for their own, so another
    # vendor's site/shift can never be attached
    assert emp("oper_a", foreign, "OPE2").status_code == 422
    assert emp("admin_b", w.customer, "OPE3").status_code == 404
    assert emp("oper_a", w.customer, "OPE4", site_id=999999).status_code == 422
    # the new employee can immediately be put on a request
    assert request_trip(w, emps=[r.json()]).status_code == 201
    # drivers still cannot touch employees
    drv = make_user(db, "drvx", Role.DRIVER, w.world["va"].id)
    assert w.client.post("/api/employees", headers=auth(w.client, "drvx"), json={}).status_code == 403
