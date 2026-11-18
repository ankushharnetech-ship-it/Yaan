import base64
import hashlib
import hmac

import pytest
from sqlalchemy import select

from app.models import Role, SmsLog
from app.services import sms
from tests.conftest import GEO, auth, employee_extras, make_user
from app.services import otp
from tests.test_trips import create, driver_world, iso, lk, trip_body, w  # noqa: F401  (fixtures)


def logs(db):
    db.expire_all()
    return list(db.scalars(select(SmsLog).order_by(SmsLog.id)))


# ---------------------------------------------------------------- phone numbers / templates
@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "+919876543210"), ("098765 43210", "+919876543210"), ("+91 98765-43210", "+919876543210"),
    ("0091 9876543210", "+919876543210"), ("+14155550123", "+14155550123"), ("(415) 555-0123", "+914155550123"),
])
def test_phone_normalisation(raw, expected):
    assert sms.normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "abc", "123", "+0123456789", "++919876543210"])
def test_invalid_phones_rejected(raw):
    assert sms.normalize_phone(raw) is None


# ---------------------------------------------------------------- on trip creation
def test_trip_creation_sends_sms_to_driver_and_every_passenger(w, db, smsbox):
    t = create(w, emps=[w.m1, w.f1]).json()
    rows = logs(db)
    assert len(rows) == 3 and {r.status for r in rows} == {"sent"} and len(smsbox.sent) == 3
    assert sorted(r.recipient_type for r in rows) == ["driver", "employee", "employee"]
    assert all(r.trip_id == t["id"] and r.phone.startswith("+91") and r.provider_message_id for r in rows)

    drv = next(r for r in rows if r.recipient_type == "driver")
    for must in ("YAAN", t["code"], "07 Jan 2030", "Acme", "HQ", "MH01AA0004", "Home", "Office"):
        assert must in drv.body, must
    emp = next(r for r in rows if r.recipient_name == "M1 E")
    # a passenger's pickup on a Pickup trip is their OWN address (all test employees live at GEO's address), not the trip-level one
    for must in ("YAAN", t["code"], "07 Jan 2030", "Pickup: 1 Test Road, Pune", "Drop: Office", "L1 D", "9000000001", "MH01AA0004"):
        assert must in emp.body, must


def test_employee_address_is_pickup_on_pickup_trips_and_drop_on_drop_trips(w, db):
    emp = w.post("/api/employees", dict(customer_id=w.customer["id"], employee_code="HOME", first_name="Hema", last_name="Home",
                                        mobile="9876500000", gender="male", **{**GEO, "address": "7 Lotus Lane, Pune"},
                                        **employee_extras(w.client, w.h["admin_a"], w.customer["id"], "HOME")))
    assert emp["address"] == "7 Lotus Lane, Pune" and "pickup_address" not in emp and "drop_address" not in emp
    create(w, emps=[emp])                                                      # Pickup trip: Home -> Office
    pickup_msg = next(r.body for r in logs(db) if r.recipient_type == "employee")
    assert "Pickup: 7 Lotus Lane, Pune" in pickup_msg and "Drop: Office" in pickup_msg
    drop_type = w.lk["trip_type"]["Drop"]
    create(w, emps=[emp], driver=w.d2, vehicle=w.v6, trip_type_id=drop_type, pickup_address="Office", drop_address="Somewhere")
    drop_msg = [r.body for r in logs(db) if r.recipient_type == "employee"][-1]
    assert "Pickup: Office" in drop_msg and "Drop: 7 Lotus Lane, Pune" in drop_msg
    trip = w.client.get("/api/trips", headers=w.h["admin_a"]).json()["items"][-1]
    assert w.client.get(f"/api/trips/{trip['id']}", headers=w.h["admin_a"]).json()["passengers"][0]["address"] == "7 Lotus Lane, Pune"


def test_message_time_is_in_business_timezone(w, db):
    create(w)  # 09:00 UTC == 14:30 in Asia/Kolkata
    assert "14:30" in logs(db)[0].body


def test_provider_outage_does_not_block_trip_and_can_be_retried(w, db, smsbox):
    smsbox.fail = "Twilio is down"
    r = create(w, emps=[w.m1, w.m2])
    assert r.status_code == 201                                   # the trip is the source of truth
    rows = logs(db)
    assert len(rows) == 3 and {x.status for x in rows} == {"failed"}
    assert "Twilio is down" in rows[0].failure_reason and rows[0].attempts == 1
    t = w.client.get(f"/api/trips/{r.json()['id']}", headers=w.h["admin_a"]).json()
    assert t["sms_status"] == "failed"

    smsbox.fail = None
    bad = w.client.post(f"/api/sms-logs/{rows[0].id}/retry", headers=w.h["admin_a"])
    assert bad.status_code == 200 and bad.json()["status"] == "pending"  # re-queued; delivery runs after the response
    assert logs(db)[0].status == "sent" and logs(db)[0].attempts == 2
    assert w.client.post(f"/api/sms-logs/{rows[0].id}/retry", headers=w.h["admin_a"]).status_code == 409  # not failed any more


def test_one_bad_number_does_not_stop_the_others(w, db, smsbox):
    smsbox.fail_for = {"+919876543210"}
    create(w, emps=[w.m1])
    by = {r.recipient_type: r for r in logs(db)}
    assert by["driver"].status == "sent" and by["employee"].status == "failed"


def test_invalid_phone_is_logged_not_sent(w, db, smsbox):
    db.execute(__import__("sqlalchemy").text("update drivers set contact_number='12' where id=:i"), {"i": w.d1["id"]})
    db.commit()
    create(w, emps=[w.m1])
    drv = next(r for r in logs(db) if r.recipient_type == "driver")
    assert drv.status == "failed" and "phone" in drv.failure_reason.lower()
    assert len(smsbox.sent) == 1  # only the passenger
    assert w.client.post(f"/api/sms-logs/{drv.id}/retry", headers=w.h["admin_a"]).status_code == 422


def test_no_sms_for_rejected_trip(w, db, smsbox):
    assert create(w, start=60, end=30).status_code == 422
    create(w)
    n = len(logs(db))
    assert create(w).status_code == 409                            # conflict
    assert len(logs(db)) == n


# ---------------------------------------------------------------- cancellation (on by default) & reassignment (off by default)
def test_cancellation_sends_sms_by_default(w, db, smsbox):
    t = create(w, emps=[w.m1, w.m2]).json()
    smsbox.sent.clear()
    w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "Not needed"})
    cancelled = [r for r in logs(db) if r.template.startswith("trip_cancelled")]
    assert len(cancelled) == 3 and all(r.status == "sent" and "cancelled" in r.body and t["code"] in r.body for r in cancelled)


def test_cancellation_sms_can_be_switched_off_per_vendor(w, db):
    r = w.client.put("/api/settings", headers=w.h["admin_a"], json={"sms_on_cancellation": False})
    assert r.json()["values"]["sms_on_cancellation"] is False
    t = create(w).json()
    w.client.post(f"/api/trips/{t['id']}/cancel", headers=w.h["admin_a"], json={"reason": "Not needed"})
    assert not [x for x in logs(db) if x.template.startswith("trip_cancelled")]


def test_reassignment_sms_is_off_by_default(w, db):
    t = create(w).json()
    n = len(logs(db))
    assert w.client.post(f"/api/trips/{t['id']}/assign", headers=w.h["admin_a"], json={"driver_id": w.d2["id"]}).status_code == 200
    assert len(logs(db)) == n


def test_reassignment_sms_when_enabled(w, db):
    w.client.put("/api/settings", headers=w.h["admin_a"], json={"sms_on_reassignment": True})
    t = create(w, emps=[w.m1, w.m2]).json()
    before = len(logs(db))
    w.client.post(f"/api/trips/{t['id']}/assign", headers=w.h["admin_a"], json={"driver_id": w.d2["id"]})
    new = logs(db)[before:]
    kinds = sorted(r.template for r in new)
    assert kinds == ["trip_reassigned_driver", "trip_reassigned_employee", "trip_reassigned_employee", "trip_unassigned_driver"]
    assert all(r.status == "sent" for r in new)
    emp = next(r for r in new if r.template == "trip_reassigned_employee")
    assert "L2 D" in emp.body
    # a vehicle-only change notifies passengers but not drivers
    before = len(logs(db))
    w.client.post(f"/api/trips/{t['id']}/assign", headers=w.h["admin_a"], json={"vehicle_id": w.v6["id"]})
    assert sorted({r.template for r in logs(db)[before:]}) == ["trip_reassigned_employee"]


def test_settings_permissions_and_scoping(w):
    assert w.client.get("/api/settings", headers=w.h["oper_a"]).status_code == 403
    assert w.client.put("/api/settings", headers=w.h["oper_a"], json={"sms_on_cancellation": False}).status_code == 403
    w.client.put("/api/settings", headers=w.h["admin_a"], json={"sms_on_reassignment": True, "vendor_id": w.world["vb"].id})
    # a vendor admin can only ever change their own vendor, whatever vendor_id they send
    assert w.client.get("/api/settings", headers=w.h["admin_a"]).json()["values"]["sms_on_reassignment"] is True
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["sms_on_reassignment"] is False
    # super admin: global default + per-vendor override
    w.client.put("/api/settings", headers=w.h["root"], json={"sms_on_cancellation": False})
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["sms_on_cancellation"] is False
    w.client.put("/api/settings", headers=w.h["root"], json={"vendor_id": w.world["vb"].id, "sms_on_cancellation": True})
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["sms_on_cancellation"] is True


# ---------------------------------------------------------------- preview
def test_preview_matches_what_is_sent(w, db):
    body = {k: trip_body(w)[k] for k in ("customer_id", "site_id", "trip_type_id", "scheduled_start", "pickup_address",
                                          "drop_address", "employee_ids", "driver_id", "vehicle_id")}
    r = w.client.post("/api/trips/sms-preview", headers=w.h["admin_a"], json=body)
    assert r.status_code == 200
    msgs = r.json()["messages"]
    assert [m["type"] for m in msgs] == ["driver", "employee"] and msgs[0]["phone"] == "+919000000001"
    assert not logs(db)                                          # preview sends nothing
    create(w)
    sent = {r.recipient_type: r.body for r in logs(db)}
    assert msgs[0]["message"].split(" on ", 1)[1] == sent["driver"].split(" on ", 1)[1]
    # the stored text holds the OTP token; the preview shows the same text with the OTP masked, never a real code
    assert msgs[1]["message"].split("booked", 1)[1] == otp.mask(sent["employee"]).split("booked", 1)[1]
    assert "OTP is ••••" in msgs[1]["message"]
    assert w.client.post("/api/trips/sms-preview", headers=w.h["admin_b"], json=body).status_code == 404


# ---------------------------------------------------------------- log visibility
def test_sms_log_access_is_scoped(driver_world, db):
    w = driver_world
    create(w, emps=[w.m1])                                        # driver d1
    create(w, driver=w.d2, vehicle=w.v6, emps=[w.m2])             # driver d2
    get = lambda h, qs="": w.client.get(f"/api/sms-logs{qs}", headers=h).json()  # noqa: E731
    assert get(w.h["admin_a"])["total"] == 4
    assert get(w.h["root"])["total"] == 4
    assert get(w.h["admin_b"])["total"] == 0                       # other vendor sees nothing
    mine = get(w.dh1)
    assert mine["total"] == 1 and mine["items"][0]["recipient_type"] == "driver"   # only their own message
    assert get(w.h["admin_a"], "?status=failed")["total"] == 0
    assert get(w.h["admin_a"], "?recipient_type=employee")["total"] == 2
    assert w.client.post("/api/sms-logs/1/retry", headers=w.dh1).status_code == 403
    assert w.client.post("/api/sms-logs/1/retry", headers=w.h["admin_b"]).status_code == 404


def test_trip_list_shows_sms_status_but_not_to_drivers(driver_world):
    w = driver_world
    create(w)
    assert w.client.get("/api/trips", headers=w.h["admin_a"]).json()["items"][0]["sms_status"] == "sent"
    assert w.client.get("/api/trips", headers=w.dh1).json()["items"][0]["sms_status"] is None


# ---------------------------------------------------------------- Twilio delivery webhook
def _sign(url, params, token):
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_twilio_callback_updates_delivery_and_checks_signature(w, db, monkeypatch):
    from app.core.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "twilio_auth_token", "tok_test")
    monkeypatch.setattr(s, "public_base_url", "https://api.example.com")
    create(w)
    row = logs(db)[0]
    url = "https://api.example.com/api/webhooks/twilio/status"
    params = {"MessageSid": row.provider_message_id, "MessageStatus": "delivered"}

    bad = w.client.post("/api/webhooks/twilio/status", data=params, headers={"X-Twilio-Signature": "nope"})
    assert bad.status_code == 403 and logs(db)[0].status == "sent"
    ok = w.client.post("/api/webhooks/twilio/status", data=params, headers={"X-Twilio-Signature": _sign(url, params, "tok_test")})
    assert ok.status_code == 200 and logs(db)[0].status == "delivered" and logs(db)[0].delivered_at
    # a late "sent" callback must not downgrade a delivered message
    late = {"MessageSid": row.provider_message_id, "MessageStatus": "sent"}
    w.client.post("/api/webhooks/twilio/status", data=late, headers={"X-Twilio-Signature": _sign(url, late, "tok_test")})
    assert logs(db)[0].status == "delivered"
    # carrier failure is recorded
    other = logs(db)[1]
    fail = {"MessageSid": other.provider_message_id, "MessageStatus": "undelivered", "ErrorCode": "30003"}
    w.client.post("/api/webhooks/twilio/status", data=fail, headers={"X-Twilio-Signature": _sign(url, fail, "tok_test")})
    assert logs(db)[1].status == "failed" and "30003" in logs(db)[1].failure_reason
