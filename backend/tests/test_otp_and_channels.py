"""Drop-off OTPs, the notification channel settings (SMS / Email), and the newly mandatory master-data fields."""
import re

import pytest
from sqlalchemy import select, text

from app.models import AuditLog, Role, TripPassenger
from app.services import otp
from tests.conftest import CONTACT, GEO, VENDOR, auth, employee_extras, make_user, otp_codes, verify_all_otps
from tests.test_request_workflow import assign, request_trip
from tests.test_trips import create, driver_world, lk, trip_body, w  # noqa: F401  (fixtures)

DAY = "range=custom&date_from=2030-01-07&date_to=2030-01-07"


def drive(w, trip, *steps, who=None):
    h = who or w.dh1
    for s in steps:
        r = w.client.post(f"/api/trips/{trip['id']}/status", headers=h, json={"status": s})
        assert r.status_code == 200, (s, r.text)


def verify(w, trip, employee_id, code, who=None):
    return w.client.post(f"/api/trips/{trip['id']}/passengers/{employee_id}/verify-otp", headers=who or w.dh1, json={"otp": code})


def not_dropped(w, trip, employee_id, reason="Did not turn up", who=None):
    return w.client.post(f"/api/trips/{trip['id']}/passengers/{employee_id}/not-dropped", headers=who or w.dh1, json={"reason": reason})


def give_driver_email(db, *drivers):
    for d in drivers:
        db.execute(text("update drivers set email = :e where id = :i"), {"e": f"driver{d['id']}@example.com", "i": d["id"]})
    db.commit()


def wrong_for(code):
    return "0000" if code != "0000" else "1111"


def settings(w, who="admin_a", **kw):
    r = w.client.put("/api/settings", headers=w.h[who] if isinstance(who, str) else who, json=kw)
    assert r.status_code == 200, r.text
    return r.json()["values"]


def trip_of(w, trip, who):
    return w.client.get(f"/api/trips/{trip['id']}", headers=w.h[who] if isinstance(who, str) else who).json()


# ================================================================ newly mandatory fields
def test_employee_site_shift_and_email_are_mandatory(w):
    base = dict(customer_id=w.customer["id"], first_name="N", last_name="E", mobile="9876543210", gender="male", **GEO)
    ok_extras = lambda code: employee_extras(w.client, w.h["admin_a"], w.customer["id"], code)  # noqa: E731
    good = w.client.post("/api/employees", headers=w.h["admin_a"], json={**base, "employee_code": "OK1", **ok_extras("OK1")})
    assert good.status_code == 201
    for field in ("site_id", "shift_id", "email"):
        for blank in (None, ""):
            body = {**base, "employee_code": f"B-{field}", **ok_extras(f"B-{field}")}
            body[field] = blank
            r = w.client.post("/api/employees", headers=w.h["admin_a"], json=body)
            assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, (field, blank)
        body = {**base, "employee_code": f"M-{field}", **ok_extras(f"M-{field}")}
        del body[field]
        r = w.client.post("/api/employees", headers=w.h["admin_a"], json=body)
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, field
    bad_email = w.client.post("/api/employees", headers=w.h["admin_a"], json={**base, "employee_code": "BE", **ok_extras("BE"), "email": "not-an-email"})
    assert bad_email.status_code == 422 and bad_email.json()["detail"][0]["loc"][-1] == "email"
    # updates are held to the same rule (an Operator editing an employee too)
    full = {k: good.json()[k] for k in ("employee_code", "first_name", "last_name", "mobile", "gender", "address", "latitude", "longitude", "site_id", "shift_id", "email")}
    for who in ("admin_a", "oper_a"):
        for field in ("site_id", "shift_id", "email"):
            r = w.client.put(f"/api/employees/{good.json()['id']}", headers=w.h[who], json={**full, field: None})
            assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, (who, field)
    assert w.client.put(f"/api/employees/{good.json()['id']}", headers=w.h["oper_a"], json={**full, "first_name": "Renamed"}).status_code == 200


def test_employee_shift_and_site_must_belong_to_the_customer(w):
    other = w.post("/api/customers", {"code": "OC", "name": "Other", **GEO, **CONTACT})
    foreign = employee_extras(w.client, w.h["admin_a"], other["id"], "FOR")
    body = dict(customer_id=w.customer["id"], employee_code="X1", first_name="N", last_name="E", mobile="9876543210", gender="male", **GEO)
    mine = employee_extras(w.client, w.h["admin_a"], w.customer["id"], "MINE")
    r = w.client.post("/api/employees", headers=w.h["admin_a"], json={**body, **mine, "shift_id": foreign["shift_id"]})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "shift_id"
    r = w.client.post("/api/employees", headers=w.h["admin_a"], json={**body, **mine, "site_id": foreign["site_id"]})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "site_id"


def test_customer_contact_person_and_email_are_mandatory(w):
    base = {"code": "CC", "name": "Contact Co", **GEO, **CONTACT}
    for field in ("contact_person", "email"):
        for blank in (None, "", "   "):
            r = w.client.post("/api/customers", headers=w.h["admin_a"], json={**base, field: blank})
            assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, (field, blank)
        gone = dict(base)
        del gone[field]
        assert w.client.post("/api/customers", headers=w.h["admin_a"], json=gone).json()["detail"][0]["loc"][-1] == field
    assert w.client.post("/api/customers", headers=w.h["admin_a"], json={**base, "email": "nope"}).status_code == 422
    ok = w.client.post("/api/customers", headers=w.h["admin_a"], json=base)
    assert ok.status_code == 201 and ok.json()["contact_person"] == "Front Desk" and ok.json()["email"] == "desk@example.com"
    r = w.client.put(f"/api/customers/{ok.json()['id']}", headers=w.h["admin_a"], json={**base, "contact_person": None})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "contact_person"


def test_vendor_primary_contact_email_and_address_are_mandatory(w):
    base = {"name": "Delta Cabs", "code": "DLT", **VENDOR}
    for field in ("contact_name", "email", "address"):
        for blank in (None, "", "  "):
            r = w.client.post("/api/vendors", headers=w.h["root"], json={**base, field: blank})
            assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, (field, blank)
        gone = dict(base)
        del gone[field]
        assert w.client.post("/api/vendors", headers=w.h["root"], json=gone).json()["detail"][0]["loc"][-1] == field
    ok = w.client.post("/api/vendors", headers=w.h["root"], json=base)                      # mobile stays optional
    assert ok.status_code == 201 and ok.json()["contact_name"] == "Vera Vendor" and ok.json()["address"] == "1 Depot Road, Pune"
    r = w.client.put(f"/api/vendors/{ok.json()['id']}", headers=w.h["root"], json={**base, "address": None})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "address"


def test_driver_email_is_required_and_validated(w):
    body = dict(first_name="E", last_name="D", contact_number="9000000011", gender="male",
                license_type_id=w.lk["license_type"]["LMV"], license_number="EM1", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road")
    assert w.client.post("/api/drivers", headers=w.h["admin_a"], json={**body, "email": "d@example.com"}).json()["email"] == "d@example.com"
    assert w.client.post("/api/drivers", headers=w.h["admin_a"], json={**body, "license_number": "EM0"}).status_code == 422
    ok = w.client.post("/api/drivers", headers=w.h["admin_a"], json={**body, "license_number": "EM2", "email": "d@example.com"})
    assert ok.status_code == 201 and ok.json()["email"] == "d@example.com"
    assert w.client.post("/api/drivers", headers=w.h["admin_a"], json={**body, "license_number": "EM3", "email": "bad"}).status_code == 422


# ================================================================ OTP issuing
def test_otps_exist_only_once_a_trip_is_assigned(w, db):
    t = request_trip(w, emps=[w.m1, w.m2]).json()
    assert otp_codes(t["id"]) == {}                                                       # a request has no OTPs
    assert {p["drop_status"] for p in trip_of(w, t, "admin_a")["passengers"]} == {"none"}
    assert assign(w, t).status_code == 200
    codes = otp_codes(t["id"])
    assert set(codes) == {w.m1["id"], w.m2["id"]}                                          # one per employee
    assert all(re.fullmatch(r"\d{4}", c) for c in codes.values())                          # 4 digits (confirmed)
    assert {p["drop_status"] for p in trip_of(w, t, "admin_a")["passengers"]} == {"pending"}


def test_each_employee_gets_their_own_otp_and_it_is_derived_not_stored(w, db):
    emps = [w.m1, w.m2, w.m3, w.f1, w.f2]
    seen = set()
    for i in range(6):   # several trips: the same employee gets a different OTP each time
        t = create(w, emps=[w.m1], start=i * 200, end=i * 200 + 60, driver=w.d1 if i % 2 == 0 else w.d2, vehicle=w.v4 if i % 2 == 0 else w.v6).json()
        seen.add(otp_codes(t["id"])[w.m1["id"]])
    assert len(seen) > 1
    t = create(w, emps=emps, vehicle=w.v6, start=2000, end=2060).json()
    seeds = [p.otp_seed for p in db.scalars(select(TripPassenger).where(TripPassenger.trip_id == t["id"]))]
    assert len(set(seeds)) == 5 and all(re.fullmatch(r"[0-9a-f]{32}", s) for s in seeds)
    # the OTP depends on the server secret, so the stored seeds alone are useless
    from app.core.config import get_settings
    cfg = get_settings()
    original = cfg.jwt_secret
    under_real_secret = [otp.code(p.otp_seed, t["id"], p.employee_id) for p in db.scalars(select(TripPassenger).where(TripPassenger.trip_id == t["id"]).order_by(TripPassenger.id))]
    try:
        cfg.jwt_secret = "a-completely-different-secret-value-1234567890"
        under_other_secret = [otp.code(p.otp_seed, t["id"], p.employee_id) for p in db.scalars(select(TripPassenger).where(TripPassenger.trip_id == t["id"]).order_by(TripPassenger.id))]
    finally:
        cfg.jwt_secret = original
    assert under_real_secret != under_other_secret


def test_direct_creation_by_an_admin_also_issues_otps(w):
    t = create(w, emps=[w.m1, w.f1]).json()
    assert len(otp_codes(t["id"])) == 2


def test_employees_receive_their_otp_by_sms_and_drivers_never_do(w, db, smsbox):
    t = request_trip(w, emps=[w.m1, w.f1]).json()
    assert smsbox.sent == []
    assign(w, t)
    codes = otp_codes(t["id"])
    emp_msgs = {m["body"] for m in smsbox.sent if "Your OTP is" in m["body"]}
    assert len(smsbox.sent) == 3 and len(emp_msgs) == 2                                    # driver + 2 employees; each employee text differs
    for code in codes.values():
        assert sum(f"Your OTP is {code}." in m["body"] for m in smsbox.sent) == 1          # each code is in exactly one message
    driver_msg = next(m for m in smsbox.sent if "New trip" in m["body"])
    assert "OTP" not in driver_msg["body"]                                                  # the driver is never given one
    assert "Share it with the driver only when you reach your drop point" in next(iter(emp_msgs))
    assert all("[OTP]" not in m["body"] for m in smsbox.sent)                              # the token never goes out


def test_stored_and_displayed_notifications_never_contain_the_code(w, db, smsbox):
    settings(w, notify_email_enabled=True)
    give_driver_email(db, w.d1)
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    code = otp_codes(t["id"])[w.m1["id"]]
    for table in ("sms_logs", "email_logs"):
        bodies = db.execute(text(f"select body from {table} where trip_id = :t"), {"t": t["id"]}).scalars().all()
        assert bodies and all(f"OTP is {code}" not in (b or "") for b in bodies), table
        assert any("OTP is [OTP]" in (b or "") for b in bodies)                            # stored with the placeholder only
    for who in ("admin_a", "oper_a", "root"):
        for path in ("sms-logs", "email-logs"):
            blob = w.client.get(f"/api/{path}?trip_id={t['id']}", headers=w.h[who]).text
            assert f"OTP is {code}" not in blob and "[OTP]" not in blob and "OTP is ••••" in blob, (who, path)
    audit = " ".join(str(d) for d in db.scalars(select(AuditLog.detail)))
    assert f"OTP is {code}" not in audit and f'"otp": "{code}"' not in audit


def test_preview_shows_a_masked_otp(w):
    body = {k: trip_body(w)[k] for k in ("customer_id", "site_id", "trip_type_id", "scheduled_start", "pickup_address", "drop_address", "employee_ids", "driver_id", "vehicle_id")}
    r = w.client.post("/api/trips/sms-preview", headers=w.h["admin_a"], json=body).json()
    emp = next(m for m in r["messages"] if m["type"] == "employee")
    assert "OTP is ••••" in emp["message"] and "[OTP]" not in emp["message"] and r["channels"] == {"sms": True, "email": False}


# ================================================================ who can see the OTP
def test_only_the_requesting_operator_sees_the_otp(w, db):
    make_user(db, "oper_a2", Role.OPERATOR, w.world["va"].id, customer_id=w.customer["id"])
    t = request_trip(w, who="oper_a", emps=[w.m1, w.m2]).json()
    assert all("otp" not in p for p in trip_of(w, t, "oper_a")["passengers"])               # nothing before assignment
    assign(w, t)
    codes = otp_codes(t["id"])
    mine = trip_of(w, t, "oper_a")["passengers"]
    assert {p["employee_id"]: p["otp"] for p in mine} == codes                              # the requester sees every OTP
    listing = w.client.get("/api/trips?view=all", headers=w.h["oper_a"]).json()["items"][0]["passengers"]
    assert {p["employee_id"]: p["otp"] for p in listing} == codes
    other = auth(w.client, "oper_a2")
    for who in (other, w.h["admin_a"], w.h["root"]):
        assert all("otp" not in p for p in w.client.get(f"/api/trips/{t['id']}", headers=who).json()["passengers"]), who
        assert all("otp" not in p for it in w.client.get("/api/trips?view=all", headers=who).json()["items"] for p in it["passengers"]), who
    assert w.client.get(f"/api/trips/{t['id']}", headers=w.h["admin_b"]).status_code == 404
    # a driver never sees it either (even while the trip is in progress)
    make_user(db, "drv1", Role.DRIVER, w.world["va"].id, driver_id=w.d1["id"])
    dh = auth(w.client, "drv1")
    drive(w, t, "accepted", "started", who=dh)
    seen = w.client.get(f"/api/trips/{t['id']}", headers=dh).json()
    assert all("otp" not in p for p in seen["passengers"])
    assert {p["drop_status"] for p in seen["passengers"]} == {"pending"}


def test_a_trip_an_admin_created_shows_no_otp_to_any_operator(w):
    t = create(w, emps=[w.m1]).json()                                                       # created by the Vendor Admin
    assert all("otp" not in p for p in trip_of(w, t, "oper_a")["passengers"])
    assert all("otp" not in p for p in trip_of(w, t, "admin_a")["passengers"])


def test_otp_disappears_once_used_or_the_trip_ends(w, db):
    t = request_trip(w, emps=[w.m1, w.m2]).json()
    assign(w, t)
    make_user(db, "drv1", Role.DRIVER, w.world["va"].id, driver_id=w.d1["id"])
    dh = auth(w.client, "drv1")
    drive(w, t, "accepted", "started", who=dh)
    codes = otp_codes(t["id"])
    assert verify(w, t, w.m1["id"], codes[w.m1["id"]], who=dh).status_code == 200
    ps = {p["employee_id"]: p for p in trip_of(w, t, "oper_a")["passengers"]}
    assert "otp" not in ps[w.m1["id"]] and ps[w.m1["id"]]["drop_status"] == "verified"        # used -> hidden
    assert ps[w.m2["id"]]["otp"] == codes[w.m2["id"]]
    assert verify(w, t, w.m2["id"], codes[w.m2["id"]], who=dh).status_code == 200
    drive(w, t, "completed", who=dh)
    assert all("otp" not in p for p in trip_of(w, t, "oper_a")["passengers"])               # finished -> hidden
    cancelled = request_trip(w, emps=[w.m1], start=500, end=560).json()
    assign(w, cancelled, driver=w.d2, vehicle=w.v6)
    assert any("otp" in p for p in trip_of(w, cancelled, "oper_a")["passengers"])
    w.client.post(f"/api/trips/{cancelled['id']}/cancel", headers=w.h["admin_a"], json={"reason": "no longer needed"})
    assert all("otp" not in p for p in trip_of(w, cancelled, "oper_a")["passengers"])


# ================================================================ driver verification
@pytest.fixture
def started(driver_world):
    w = driver_world
    w.t = request_trip(w, emps=[w.m1, w.m2, w.f1]).json()
    assign(w, w.t)
    drive(w, w.t, "accepted", "started")
    w.codes = otp_codes(w.t["id"])
    return w


def test_driver_verifies_each_employee_with_their_own_otp(started, db):
    w = started
    a, b = w.m1["id"], w.m2["id"]
    fresh = otp_codes(w.t["id"])
    r = verify(w, w.t, a, fresh[a])
    assert r.status_code == 200
    ps = {p["employee_id"]: p for p in r.json()["passengers"]}
    assert ps[a]["drop_status"] == "verified" and ps[a]["otp_verified_at"] and "otp" not in ps[a]
    assert ps[b]["drop_status"] == "pending" and r.json()["drops_resolved"] == 1
    assert verify(w, w.t, a, fresh[a]).status_code == 409                                  # already dropped
    assert "trip.otp_verified" in set(db.scalars(select(AuditLog.action)))


def test_an_otp_only_works_for_its_own_employee(started):
    w = started
    codes = otp_codes(w.t["id"])
    a, b = w.m1["id"], w.m2["id"]
    if codes[a] == codes[b]:
        pytest.skip("two employees happened to draw the same 4-digit code")
    r = verify(w, w.t, a, codes[b])
    assert r.status_code == 422 and r.json()["detail"][0]["code"] == "otp_wrong"
    assert verify(w, w.t, b, codes[b]).status_code == 200


def test_wrong_otp_is_counted_and_five_tries_lock_that_employee(started, db):
    w = started
    a = w.m1["id"]
    real = w.codes[a]
    bad = wrong_for(real)
    for left in (4, 3, 2, 1):
        r = verify(w, w.t, a, bad)
        assert r.status_code == 422 and f"{left} {'try' if left == 1 else 'tries'} left" in r.json()["detail"][0]["msg"]
    locked = verify(w, w.t, a, bad)
    assert locked.status_code == 423 and locked.json()["detail"][0]["code"] == "otp_locked"
    assert verify(w, w.t, a, real).status_code == 423                                       # even the right code is refused now
    mine = {p["employee_id"]: p for p in trip_of(w, w.t, "admin_a")["passengers"]}
    assert mine[a]["otp_locked"] is True and mine[w.m2["id"]]["otp_locked"] is False       # others are unaffected
    assert verify(w, w.t, w.m2["id"], w.codes[w.m2["id"]]).status_code == 200
    actions = list(db.scalars(select(AuditLog.action)))
    assert actions.count("trip.otp_failed") == 4 and "trip.otp_locked" in actions
    assert real not in " ".join(str(d) for d in db.scalars(select(AuditLog.detail)))        # attempts are logged, never codes


def test_verification_rules(driver_world, db):
    w = driver_world
    t = request_trip(w, emps=[w.m1]).json()
    code_ep = f"/api/trips/{t['id']}/passengers/{w.m1['id']}/verify-otp"
    assert w.client.post(code_ep, headers=w.dh1, json={"otp": "1234"}).status_code == 404   # a request is not the driver's trip yet
    assign(w, t)
    codes = otp_codes(t["id"])
    assert verify(w, t, w.m1["id"], codes[w.m1["id"]]).status_code == 409                   # not started yet
    drive(w, t, "accepted")
    assert verify(w, t, w.m1["id"], codes[w.m1["id"]]).status_code == 409                   # accepted is not enough
    drive(w, t, "started")
    assert verify(w, t, 999999, "1234").status_code == 404                                  # not on this trip
    assert verify(w, t, w.m1["id"], codes[w.m1["id"]], who=w.dh2).status_code == 404        # another driver's trip
    for who in ("admin_a", "oper_a", "root"):
        assert verify(w, t, w.m1["id"], codes[w.m1["id"]], who=w.h[who]).status_code == 403, who   # only drivers verify
        assert not_dropped(w, t, w.m1["id"], who=w.h[who]).status_code == 403, who
    assert w.client.post(code_ep, headers=w.dh1, json={"otp": ""}).status_code == 422
    assert w.client.post(code_ep, headers=w.dh1, json={}).status_code == 422
    assert w.client.post(code_ep, json={"otp": "1234"}).status_code == 401
    assert verify(w, t, w.m1["id"], f" {codes[w.m1['id']]} ").status_code == 200            # stray spaces are forgiven


# ================================================================ ending the trip
def test_trip_cannot_end_until_every_employee_is_dropped(started):
    w = started
    end = lambda: w.client.post(f"/api/trips/{w.t['id']}/status", headers=w.dh1, json={"status": "completed"})  # noqa: E731
    r = end()
    assert r.status_code == 409 and r.json()["detail"][0]["code"] == "otp_pending"
    assert "3 employees still to be dropped" in r.json()["detail"][0]["msg"] and w.m1["first_name"] in r.json()["detail"][0]["msg"]
    verify(w, w.t, w.m1["id"], w.codes[w.m1["id"]])
    assert "2 employees still to be dropped" in end().json()["detail"][0]["msg"]
    verify(w, w.t, w.m2["id"], w.codes[w.m2["id"]])
    assert "1 employee still to be dropped" in end().json()["detail"][0]["msg"]
    assert trip_of(w, w.t, "admin_a")["status"] == "started"                                 # still running
    verify(w, w.t, w.f1["id"], w.codes[w.f1["id"]])
    done = end()
    assert done.status_code == 200 and done.json()["status"] == "completed" and done.json()["completed_at"]


def test_not_dropped_lets_the_trip_end_and_is_flagged(started, db):
    w = started
    assert not_dropped(w, w.t, w.m1["id"], reason="").status_code == 422                   # a reason is required
    assert not_dropped(w, w.t, w.m1["id"], reason="ab").status_code == 422
    verify(w, w.t, w.m2["id"], w.codes[w.m2["id"]])
    verify(w, w.t, w.f1["id"], w.codes[w.f1["id"]])
    r = not_dropped(w, w.t, w.m1["id"], reason="Employee was on leave and did not board")
    assert r.status_code == 200
    ps = {p["employee_id"]: p for p in r.json()["passengers"]}
    assert ps[w.m1["id"]]["drop_status"] == "not_dropped" and ps[w.m1["id"]]["not_dropped_reason"].startswith("Employee was on leave")
    assert verify(w, w.t, w.m1["id"], w.codes[w.m1["id"]]).status_code == 409                # can't verify afterwards
    assert not_dropped(w, w.t, w.m1["id"]).status_code == 409                                # nor mark twice
    done = w.client.post(f"/api/trips/{w.t['id']}/status", headers=w.dh1, json={"status": "completed"})
    assert done.status_code == 200
    hist = trip_of(w, w.t, "admin_a")["history"][-1]
    assert hist["to"] == "completed" and "1 employee(s) not dropped" in hist["note"] and w.m1["first_name"] in hist["note"]
    assert "trip.passenger_not_dropped" in set(db.scalars(select(AuditLog.action)))
    # flagged for admins on the dashboard, and visible (with the reason) on the trip
    items = w.client.get(f"/api/dashboard/exceptions?{DAY}", headers=w.h["admin_a"]).json()["items"]
    assert any(i["reason"] == "not_dropped" and i["trip_id"] == w.t["id"] for i in items)
    assert trip_of(w, w.t, "oper_a")["passengers"][0]["not_dropped_reason"]


def test_a_locked_employee_can_be_marked_not_dropped_so_the_trip_is_never_stuck(started):
    w = started
    a = w.m1["id"]
    for _ in range(5):
        verify(w, w.t, a, wrong_for(w.codes[a]))
    assert verify(w, w.t, a, w.codes[a]).status_code == 423
    assert not_dropped(w, w.t, a, reason="Could not share OTP, phone lost").status_code == 200
    for e in (w.m2, w.f1):
        verify(w, w.t, e["id"], w.codes[e["id"]])
    assert w.client.post(f"/api/trips/{w.t['id']}/status", headers=w.dh1, json={"status": "completed"}).status_code == 200


def test_concurrent_verification_attempts_are_serialised(started):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi.testclient import TestClient
    from app.main import app
    w = started
    a = w.m1["id"]
    bad = wrong_for(w.codes[a])
    clients = [TestClient(app) for _ in range(8)]
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda c: c.post(f"/api/trips/{w.t['id']}/passengers/{a}/verify-otp", headers=w.dh1, json={"otp": bad}).status_code, clients))
    assert sorted(codes) == [422, 422, 422, 422, 423, 423, 423, 423]                        # exactly 5 tries counted, never more


# ================================================================ editing an assigned trip
def test_adding_and_removing_employees_on_an_assigned_trip(w, db, smsbox):
    t = request_trip(w, emps=[w.m1, w.m2]).json()
    assign(w, t)
    before = otp_codes(t["id"])
    smsbox.sent.clear()
    put = lambda emps: w.client.put(f"/api/trips/{t['id']}", headers=w.h["admin_a"], json=trip_body(w, emps=emps))  # noqa: E731
    r = put([w.m1, w.m2, w.m3])                                                             # m3 joins
    assert r.status_code == 200, r.text
    after = otp_codes(t["id"])
    assert after[w.m1["id"]] == before[w.m1["id"]] and after[w.m2["id"]] == before[w.m2["id"]]   # existing OTPs untouched
    assert w.m3["id"] in after
    assert len(smsbox.sent) == 1 and f"Your OTP is {after[w.m3['id']]}." in smsbox.sent[0]["body"]   # only the newcomer is told
    r = put([w.m2, w.m3])                                                                   # m1 leaves
    assert r.status_code == 200 and set(otp_codes(t["id"])) == {w.m2["id"], w.m3["id"]}
    assert otp_codes(t["id"])[w.m2["id"]] == before[w.m2["id"]]


def test_a_reassignment_keeps_the_same_otps(w):
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    before = otp_codes(t["id"])
    assert assign(w, t, driver=w.d2, vehicle=w.v6).status_code == 200
    assert otp_codes(t["id"]) == before


# ================================================================ notification channels
def test_defaults_are_sms_on_email_off(w, smsbox, outbox):
    assert w.client.get("/api/settings", headers=w.h["admin_a"]).json()["values"]["notify_sms_enabled"] is True
    assert w.client.get("/api/settings", headers=w.h["admin_a"]).json()["values"]["notify_email_enabled"] is False
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    assert len(smsbox.sent) == 2 and outbox.sent == []


def test_both_channels_on_notifies_everyone_both_ways(w, db, smsbox, outbox):
    settings(w, notify_email_enabled=True)
    give_driver_email(db, w.d1)
    t = request_trip(w, emps=[w.m1, w.f1]).json()
    assign(w, t)
    assert len(smsbox.sent) == 3 and len(outbox.sent) == 3                                  # driver + 2 employees, on each channel
    codes = otp_codes(t["id"])
    for code in codes.values():
        phrase = f"Your OTP is {code}."
        assert sum(phrase in m["body"] for m in smsbox.sent) == 1 and sum(phrase in m["text"] for m in outbox.sent) == 1
    drv_mail = next(m for m in outbox.sent if "assigned to you" in m["subject"])
    assert "OTP" not in drv_mail["text"] and drv_mail["to"] == f"driver{w.d1['id']}@example.com"
    emp_mails = [m for m in outbox.sent if "is booked" in m["subject"]]
    assert len(emp_mails) == 2 and {m["to"] for m in emp_mails} == {w.m1["email"], w.f1["email"]}
    assert all("[OTP]" not in m["text"] for m in outbox.sent)
    assert {r.status for r in db.execute(text("select status from email_logs where trip_id = :t"), {"t": t["id"]}).all()} == {"sent"}
    assert trip_of(w, t, "admin_a")["notify_status"] == "sent"


def test_only_sms_or_only_email_when_just_one_is_enabled(w, db, smsbox, outbox):
    give_driver_email(db, w.d1, w.d2)
    settings(w, notify_sms_enabled=False, notify_email_enabled=True)                         # email only
    t1 = request_trip(w, emps=[w.m1]).json()
    assign(w, t1)
    assert smsbox.sent == [] and len(outbox.sent) == 2
    smsbox.sent.clear(); outbox.sent.clear()
    settings(w, notify_sms_enabled=True, notify_email_enabled=False)                         # sms only
    t2 = request_trip(w, emps=[w.m2], start=300, end=360).json()
    assign(w, t2, driver=w.d2, vehicle=w.v6)
    assert len(smsbox.sent) == 2 and outbox.sent == []


def test_both_off_sends_nothing_but_the_operator_can_still_read_out_the_otp(w, db, smsbox, outbox):
    settings(w, notify_sms_enabled=False, notify_email_enabled=False)
    t = request_trip(w, emps=[w.m1]).json()
    r = assign(w, t)
    assert r.status_code == 200 and r.json()["status"] == "assigned"                         # the trip itself is unaffected
    assert smsbox.sent == [] and outbox.sent == []
    assert db.execute(text("select count(*) from sms_logs")).scalar() == 0 and db.execute(text("select count(*) from email_logs where trip_id is not null")).scalar() == 0
    shown = trip_of(w, t, "oper_a")["passengers"][0]
    assert shown["otp"] == otp_codes(t["id"])[w.m1["id"]]
    assert trip_of(w, t, "admin_a")["notify_status"] is None


def test_the_channel_setting_governs_cancellations_and_reassignments_too(w, db, smsbox, outbox):
    give_driver_email(db, w.d1, w.d2)
    settings(w, notify_sms_enabled=False, notify_email_enabled=True, sms_on_reassignment=True)
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    outbox.sent.clear()
    assign(w, t, driver=w.d2, vehicle=w.v6)
    assert smsbox.sent == [] and {m["subject"].split(" ")[0] for m in outbox.sent} >= {"Trip", "Update"}
    outbox.sent.clear()
    w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "no longer needed"})
    assert smsbox.sent == [] and len(outbox.sent) == 2 and all("cancelled" in m["subject"].lower() for m in outbox.sent)


def test_missing_email_is_logged_not_fatal(w, db, outbox, smsbox):
    settings(w, notify_email_enabled=True)
    db.execute(text("update employees set email = null where id = :i"), {"i": w.m1["id"]})        # a pre-existing employee with no email
    db.commit()
    t = request_trip(w, emps=[w.m1, w.m2]).json()
    assert assign(w, t).status_code == 200
    rows = {r.recipient_name: r for r in db.execute(text("select recipient_name, status, failure_reason, to_email from email_logs where trip_id = :t"), {"t": t["id"]})}
    assert rows["M1 E"].status == "failed" and "email" in rows["M1 E"].failure_reason.lower()
    assert rows["M2 E"].status == "sent" and len(smsbox.sent) == 3                            # SMS and the other emails are unaffected


def test_driver_email_uses_their_own_address_else_their_logins(w, db, outbox):
    settings(w, notify_email_enabled=True)
    db.execute(text("update drivers set email = null where id = :i"), {"i": w.d1["id"]})      # legacy driver rows may have no email
    db.commit()
    make_user(db, "drv_login", Role.DRIVER, w.world["va"].id, driver_id=w.d1["id"])            # login email: drv_login@example.com
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    assert "drv_login@example.com" in {m["to"] for m in outbox.sent}                           # falls back to the linked login
    outbox.sent.clear()
    db.execute(text("update drivers set email = 'own@example.com' where id = :i"), {"i": w.d1["id"]})
    db.commit()
    t2 = request_trip(w, emps=[w.m1], start=500, end=560).json()
    assign(w, t2)
    assert "own@example.com" in {m["to"] for m in outbox.sent} and "drv_login@example.com" not in {m["to"] for m in outbox.sent}


def test_failed_emails_can_be_retried_and_are_scoped(w, db, outbox):
    give_driver_email(db, w.d1)
    settings(w, notify_email_enabled=True)
    outbox.fail = True
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    logs = w.client.get(f"/api/email-logs?trip_id={t['id']}", headers=w.h["admin_a"]).json()
    assert logs["total"] == 2 and {i["status"] for i in logs["items"]} == {"failed"} and logs["items"][0]["failure_reason"]
    assert trip_of(w, t, "admin_a")["notify_status"] == "failed"
    outbox.fail = False
    row = logs["items"][0]
    r = w.client.post(f"/api/email-logs/{row['id']}/retry", headers=w.h["admin_a"])
    assert r.status_code == 200 and r.json()["status"] == "pending"
    after = w.client.get(f"/api/email-logs?trip_id={t['id']}", headers=w.h["admin_a"]).json()["items"]
    assert {i["id"]: i["status"] for i in after}[row["id"]] == "sent" and len(outbox.sent) == 1
    assert w.client.post(f"/api/email-logs/{row['id']}/retry", headers=w.h["admin_a"]).status_code == 409   # no longer failed
    assert w.client.post(f"/api/email-logs/{row['id']}/retry", headers=w.h["admin_b"]).status_code == 404   # another vendor
    assert w.client.get("/api/email-logs", headers=w.h["admin_b"]).json()["total"] == 0
    assert w.client.get("/api/email-logs", headers=w.h["root"]).json()["total"] == 2
    assert w.client.get("/api/email-logs", headers=w.h["oper_a"]).json()["total"] == 2
    assert w.client.get("/api/email-logs").status_code == 401


def test_a_driver_only_sees_their_own_emails(driver_world, outbox):
    w = driver_world
    settings(w, notify_email_enabled=True)
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    mine = w.client.get("/api/email-logs", headers=w.dh1).json()
    assert mine["total"] == 1 and mine["items"][0]["recipient_type"] == "driver"
    assert w.client.get("/api/email-logs", headers=w.dh2).json()["total"] == 0
    assert w.client.post(f"/api/email-logs/{mine['items'][0]['id']}/retry", headers=w.dh1).status_code == 403


def test_who_may_change_the_channel_settings(w):
    assert w.client.put("/api/settings", headers=w.h["oper_a"], json={"notify_email_enabled": True}).status_code == 403
    assert w.client.get("/api/settings", headers=w.h["oper_a"]).status_code == 403
    # a Vendor Admin changes only their own vendor, whatever vendor_id they send
    w.client.put("/api/settings", headers=w.h["admin_a"], json={"notify_email_enabled": True, "vendor_id": w.world["vb"].id})
    assert w.client.get("/api/settings", headers=w.h["admin_a"]).json()["values"]["notify_email_enabled"] is True
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["notify_email_enabled"] is False
    # the Super Admin can set a default for everyone and override one vendor
    w.client.put("/api/settings", headers=w.h["root"], json={"notify_sms_enabled": False})
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["notify_sms_enabled"] is False
    w.client.put("/api/settings", headers=w.h["root"], json={"notify_sms_enabled": True, "vendor_id": w.world["vb"].id})
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["notify_sms_enabled"] is True
    assert w.client.get("/api/settings", headers=w.h["admin_a"]).json()["values"]["notify_sms_enabled"] is False


def test_settings_are_per_vendor(w, smsbox):
    settings(w, notify_sms_enabled=False)                                                    # vendor A switches SMS off
    t = request_trip(w, emps=[w.m1]).json()
    assign(w, t)
    assert smsbox.sent == []
    other_customer = w.post("/api/customers", {"code": "BC", "name": "B Co", **GEO, **CONTACT}, h=w.h["admin_b"])
    assert other_customer["vendor_id"] == w.world["vb"].id                                   # vendor B is untouched (still SMS on)
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["notify_sms_enabled"] is True


def test_account_emails_are_not_governed_by_the_trip_channels(w, outbox, client):
    settings(w, notify_sms_enabled=False, notify_email_enabled=False)
    r = client.post("/api/auth/forgot-password", json={"identifier": "admin_a"})
    assert r.status_code == 200 and len(outbox.sent) == 1                                    # password reset still goes out


# ================================================================ driver-facing trip data
def test_driver_sees_drop_progress_but_no_codes_or_phone_numbers(started):
    w = started
    seen = w.client.get(f"/api/trips/{w.t['id']}", headers=w.dh1).json()
    assert seen["drops_resolved"] == 0 and len(seen["passengers"]) == 3
    for p in seen["passengers"]:
        assert set(p) >= {"name", "drop_status", "otp_locked"} and "mobile" not in p and "otp" not in p
    verify(w, w.t, w.m1["id"], w.codes[w.m1["id"]])
    assert w.client.get(f"/api/trips/{w.t['id']}", headers=w.dh1).json()["drops_resolved"] == 1


def test_emails_are_formatted_and_addressed_by_name(w, db, smsbox, outbox):
    settings(w, notify_email_enabled=True)
    give_driver_email(db, w.d1)
    t = request_trip(w, emps=[w.m1, w.f1]).json()
    assign(w, t)
    codes = otp_codes(t["id"])
    emp = next(m for m in outbox.sent if "is booked" in m["subject"] and m["to"] == w.m1["email"])
    # greeted by name, and the name travels in the To header as well
    assert emp["to_name"] == "M1 E" and "Hello M1 E," in emp["text"] and "Hello <strong>M1 E</strong>" in emp["html"]
    # structured details instead of one long line, with the full addresses
    for label in ("Trip", "Date", "Pickup time", "Pickup", "Drop", "Driver", "Vehicle"):
        assert f"{label} " in emp["text"] and f">{label}<" in emp["html"]
    assert t["code"] in emp["html"] and "<table" in emp["html"]
    # the OTP is highlighted for the employee and is the right one; the token never leaks
    assert codes[w.m1["id"]] in emp["html"] and f"Your OTP is {codes[w.m1['id']]}." in emp["text"]
    assert "[OTP]" not in emp["html"]
    # the driver's email is addressed to them, has an action button, and never mentions an OTP
    drv = next(m for m in outbox.sent if "assigned to you" in m["subject"])
    assert drv["to_name"] and f"Hello {drv['to_name']}," in drv["text"] and "Open YAAN to accept" in drv["html"]
    assert "OTP" not in drv["text"] and "OTP" not in drv["html"]


def test_account_emails_are_formatted_and_addressed_by_name(client, world, outbox):
    from tests.test_auth_onboarding import create_user
    h = auth(client, "root")
    assert create_user(client, h, world["va"].id).status_code == 201
    m = outbox.sent[0]
    assert m["to_name"] == "Olivia Ops" and "Hello Olivia Ops," in m["text"] and "Hello <strong>Olivia Ops</strong>" in m["html"]
    assert "Set your password" in m["html"] and "token=" in m["html"] and "Username" in m["text"] and "olivia" in m["html"]
    assert client.post("/api/auth/forgot-password", json={"identifier": "olivia"}).status_code == 200
    r = outbox.sent[1]
    assert r["to_name"] == "Olivia Ops" and "Reset password" in r["html"] and "Hello Olivia Ops," in r["text"]
