import subprocess
import sys
from datetime import timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select

from app.models import AuditLog, LookupValue, Role
from app.services.compliance import today
from tests.conftest import auth, make_user
from tests.test_trips import driver_world, lk, w  # noqa: F401  (fixtures)


@pytest.fixture
def types(db):
    out = {}
    for r in db.scalars(select(LookupValue).where(LookupValue.category.in_(["driver_doc_type", "vehicle_doc_type"]))):
        out[(r.category, r.label)] = r.id
    return out


def day(n: int) -> str:
    return (today() + timedelta(days=n)).isoformat()


def add_driver_doc(w, types, expiry, h=None, driver=None, label="Driving licence", **kw):
    body = dict(subject_type="driver", driver_id=(driver or w.d1)["id"], doc_type_id=types[("driver_doc_type", label)],
                expiry_date=expiry, reference_number="DL-1")
    body.update(kw)
    return w.client.post("/api/compliance/items", headers=h or w.h["admin_a"], json=body)


def add_vehicle_doc(w, types, expiry, h=None, vehicle=None, label="Insurance", **kw):
    body = dict(subject_type="vehicle", vehicle_id=(vehicle or w.v4)["id"], doc_type_id=types[("vehicle_doc_type", label)],
                expiry_date=expiry)
    body.update(kw)
    return w.client.post("/api/compliance/items", headers=h or w.h["admin_a"], json=body)


def listing(w, kind="drivers", who="admin_a", qs=""):
    h = w.h[who] if isinstance(who, str) else who
    return w.client.get(f"/api/compliance/{kind}{'?' + qs if qs else ''}", headers=h)


# ---------------------------------------------------------------- compliance rules
def test_status_boundaries(w, types):
    for n, expected in ((-1, "expired"), (0, "expiring"), (30, "expiring"), (31, "valid"), (400, "valid")):
        r = add_driver_doc(w, types, day(n), reference_number=f"r{n}")
        assert r.status_code == 201, r.text
        assert r.json()["compliance"] == expected and r.json()["days_left"] == n, n   # valid *through* the expiry date


def test_summary_and_subject_rollup(w, types):
    add_driver_doc(w, types, day(-5))                                                # d1: expired -> non compliant
    add_driver_doc(w, types, day(200), label="Medical certificate")
    add_driver_doc(w, types, day(10), driver=w.d2)                                   # d2: expiring
    d = listing(w).json()
    assert d["summary"]["documents"] == {"total": 3, "valid": 1, "expiring": 1, "expired": 1}
    assert d["summary"]["subjects"] == {"total": 2, "compliant": 0, "expiring": 1, "non_compliant": 1, "no_documents": 0}
    by = {s["name"]: s["state"] for s in d["subjects"]}
    assert by == {"L1 D": "non_compliant", "L2 D": "expiring"}
    # a vehicle with no documents is reported as such, not as compliant
    v = listing(w, "vehicles").json()["summary"]["subjects"]
    assert v["total"] == 3 and v["no_documents"] == 3 and v["compliant"] == 0
    add_vehicle_doc(w, types, day(300))
    assert listing(w, "vehicles").json()["summary"]["subjects"]["compliant"] == 1


def test_warning_window_is_configurable_per_vendor(w, types):
    add_driver_doc(w, types, day(45))
    assert listing(w).json()["items"][0]["compliance"] == "valid"
    r = w.client.put("/api/settings", headers=w.h["admin_a"], json={"compliance_expiry_warning_days": 60})
    assert r.json()["values"]["compliance_expiry_warning_days"] == 60
    assert listing(w).json()["items"][0]["compliance"] == "expiring"
    assert w.client.put("/api/settings", headers=w.h["admin_a"], json={"compliance_expiry_warning_days": 0}).status_code == 422
    assert w.client.get("/api/settings", headers=w.h["admin_b"]).json()["values"]["compliance_expiry_warning_days"] == 30


def test_filters_search_and_retire(w, types):
    a = add_driver_doc(w, types, day(-2), reference_number="ABC-123").json()
    add_driver_doc(w, types, day(90), label="Police verification", reference_number="PV-9")
    add_driver_doc(w, types, day(5), driver=w.d2, label="Other", title="Hazmat card", reference_number="HZ")
    assert listing(w, qs="status=expired").json()["total"] == 1
    assert listing(w, qs="status=expiring").json()["items"][0]["title"] == "Hazmat card"
    assert listing(w, qs="q=abc-1").json()["total"] == 1
    assert listing(w, qs="q=hazmat").json()["total"] == 1
    assert listing(w, qs="q=police").json()["total"] == 1                      # matches the document type name
    assert listing(w, qs=f"subject_id={w.d2['id']}").json()["total"] == 1
    assert listing(w, qs=f"doc_type_id={types[('driver_doc_type', 'Police verification')]}").json()["total"] == 1
    # retiring (e.g. after renewal) removes it from compliance but keeps the record
    r = w.client.patch(f"/api/compliance/items/{a['id']}/status", headers=w.h["admin_a"], json={"status": "inactive"})
    assert r.status_code == 200
    assert listing(w, qs="status=expired").json()["total"] == 0
    assert listing(w, qs="include_retired=true").json()["total"] == 3
    assert listing(w).json()["summary"]["documents"]["expired"] == 0


def test_validation(w, types):
    assert add_driver_doc(w, types, day(5), issue_date=day(10)).status_code == 422                     # expiry before issue
    both = add_driver_doc(w, types, day(5), vehicle_id=w.v4["id"])
    assert both.status_code == 422
    wrong_type = w.client.post("/api/compliance/items", headers=w.h["admin_a"], json=dict(
        subject_type="vehicle", vehicle_id=w.v4["id"], doc_type_id=types[("driver_doc_type", "Driving licence")], expiry_date=day(5)))
    assert wrong_type.status_code == 422 and wrong_type.json()["detail"][0]["loc"][-1] == "doc_type_id"
    no_expiry = w.client.post("/api/compliance/items", headers=w.h["admin_a"], json=dict(
        subject_type="driver", driver_id=w.d1["id"], doc_type_id=types[("driver_doc_type", "Driving licence")]))
    assert no_expiry.status_code == 422
    it = add_driver_doc(w, types, day(5)).json()
    moved = w.client.put(f"/api/compliance/items/{it['id']}", headers=w.h["admin_a"], json=dict(
        subject_type="driver", driver_id=w.d2["id"], doc_type_id=it["doc_type_id"], expiry_date=day(9)))
    assert moved.status_code == 422                                                                    # cannot move to another driver
    ok = w.client.put(f"/api/compliance/items/{it['id']}", headers=w.h["admin_a"], json=dict(
        doc_type_id=it["doc_type_id"], expiry_date=day(365), reference_number="RENEWED"))
    assert ok.status_code == 200 and ok.json()["compliance"] == "valid" and ok.json()["reference_number"] == "RENEWED"


# ---------------------------------------------------------------- compliance access
def test_roles_and_isolation(driver_world, types):
    w = driver_world
    mine = add_driver_doc(w, types, day(-1)).json()
    add_driver_doc(w, types, day(50), driver=w.d2)
    # operators: read-only
    assert listing(w, who="oper_a").json()["total"] == 2
    assert add_driver_doc(w, types, day(5), h=w.h["oper_a"]).status_code == 403
    assert w.client.patch(f"/api/compliance/items/{mine['id']}/status", headers=w.h["oper_a"], json={"status": "inactive"}).status_code == 403
    # drivers: only their own documents, never vehicles
    own = listing(w, who=w.dh1).json()
    assert own["total"] == 1 and own["items"][0]["subject_name"] == "L1 D" and own["summary"]["subjects"]["total"] == 1
    assert listing(w, "vehicles", who=w.dh1).status_code == 403
    assert add_driver_doc(w, types, day(5), h=w.dh1).status_code == 403
    # other vendor: cannot see, create for, edit or retire
    assert listing(w, who="admin_b").json()["total"] == 0 and listing(w, who="admin_b").json()["summary"]["subjects"]["total"] == 0
    assert add_driver_doc(w, types, day(5), h=w.h["admin_b"]).status_code == 404
    body = dict(doc_type_id=mine["doc_type_id"], expiry_date=day(9))
    assert w.client.put(f"/api/compliance/items/{mine['id']}", headers=w.h["admin_b"], json=body).status_code == 404
    assert w.client.patch(f"/api/compliance/items/{mine['id']}/status", headers=w.h["admin_b"], json={"status": "inactive"}).status_code == 404
    # super admin sees all and can narrow by vendor
    assert listing(w, who="root").json()["total"] == 2
    assert listing(w, who="root", qs=f"vendor_id={w.world['vb'].id}").json()["total"] == 0


def test_compliance_reports_and_export(w, types):
    add_driver_doc(w, types, day(-3))
    add_vehicle_doc(w, types, day(10))
    rep = w.client.get("/api/reports/compliance-drivers", headers=w.h["admin_a"]).json()
    assert rep["summary"]["Expired"] == 1 and rep["rows"][0]["state"] == "Expired" and rep["rows"][0]["subject"] == "L1 D"
    x = w.client.get("/api/reports/compliance-vehicles?format=xlsx", headers=w.h["admin_a"])
    assert x.status_code == 200
    ws = load_workbook(BytesIO(x.content)).active
    flat = [c.value for row in ws.iter_rows() for c in row]
    assert "MH01AA0004" in flat and "About to expire" in flat
    assert w.client.get("/api/reports/compliance-drivers", headers=w.h["admin_b"]).json()["rows"] == []


def test_compliance_audited(w, types, db):
    it = add_driver_doc(w, types, day(5)).json()
    w.client.patch(f"/api/compliance/items/{it['id']}/status", headers=w.h["admin_a"], json={"status": "inactive"})
    assert {"compliance.created", "compliance.retired"} <= set(db.scalars(select(AuditLog.action)))


# ---------------------------------------------------------------- hardening
def test_request_id_and_security_headers(client, world, db):
    r = client.get("/api/health")
    assert len(r.headers["x-request-id"]) >= 8
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"
    assert client.get("/api/health", headers={"X-Request-ID": "trace-abc-12345"}).headers["x-request-id"] == "trace-abc-12345"
    assert client.get("/api/health", headers={"X-Request-ID": "bad id\r\n<script>"}).headers["x-request-id"] != "bad id\r\n<script>"
    # the same correlation id ends up on the audit trail
    res = client.post("/api/auth/login", json={"username": "root", "password": "Sup3rSecret!x"}, headers={"X-Request-ID": "corr-id-987654"})
    assert res.status_code == 200
    db.expire_all()
    assert db.scalar(select(AuditLog.request_id).where(AuditLog.action == "auth.login")) == "corr-id-987654"


def test_reset_password_endpoint_is_rate_limited(client, world):
    codes = [client.post("/api/auth/reset-password", json={"token": "x" * 20, "new_password": "Whatever#12345"}).status_code for _ in range(10)]
    assert codes[:8] == [400] * 8 and codes[8:] == [429, 429]


def test_production_refuses_default_secret():
    env = {"ENVIRONMENT": "production", "JWT_SECRET": "dev-only-change-me", "PATH": ""}
    p = subprocess.run([sys.executable, "-c", "import app.main"], env={**env, "SYSTEMROOT": "C:\\Windows"}, capture_output=True, text=True)
    assert p.returncode != 0 and "JWT_SECRET" in p.stderr
    ok = subprocess.run([sys.executable, "-c", "import app.main; print('fine')"],
                        env={**env, "JWT_SECRET": "x" * 40, "SYSTEMROOT": "C:\\Windows"}, capture_output=True, text=True)
    assert ok.returncode == 0 and "fine" in ok.stdout


def test_docs_hidden_in_production():
    p = subprocess.run([sys.executable, "-c", "from app.main import app; print(app.docs_url, app.openapi_url)"],
                       env={"ENVIRONMENT": "production", "JWT_SECRET": "y" * 40, "SYSTEMROOT": "C:\\Windows"}, capture_output=True, text=True)
    assert p.stdout.strip() == "None None", p.stderr
