import os

# Must be set before the app is imported so everything binds to the test database.
os.environ["DATABASE_URL"] = "postgresql+psycopg://yaan:yaan_dev_2026@localhost:5432/yaan_test"
os.environ["SENDGRID_API_KEY"] = ""
os.environ["ZEPTOMAIL_API_KEY"] = ""  # tests must never send real email
os.environ["SMTP_HOST"] = ""
for _k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"):  # tests must never reach Twilio
    os.environ[_k] = ""
os.environ["JWT_SECRET"] = "test-secret-test-secret-test-secret-123456"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Role, User, Vendor  # noqa: E402
from app.services import auth_service, email as email_mod  # noqa: E402

PASSWORD = "Sup3rSecret!x"
# Customers and employees must now have an address and coordinates.
GEO = dict(address="1 Test Road, Pune", latitude=18.5204, longitude=73.8567)
# Customers also need a contact person and email; vendors need a primary contact, email and address.
CONTACT = dict(contact_person="Front Desk", email="desk@example.com")
VENDOR = dict(contact_name="Vera Vendor", email="vendor@example.com", address="1 Depot Road, Pune")


def otp_codes(trip_id):
    """{employee_id: code} for a trip, computed the way the server does (test-only: no API ever returns these to a driver)."""
    from sqlalchemy import select as _select
    from app.models import TripPassenger
    from app.services import otp as _otp
    with SessionLocal() as s:
        return {p.employee_id: _otp.code(p.otp_seed, trip_id, p.employee_id)
                for p in s.scalars(_select(TripPassenger).where(TripPassenger.trip_id == trip_id)) if p.otp_seed}


def verify_all_otps(client, driver_headers, trip_id):
    """The driver enters every employee's OTP at the drop point."""
    for eid, code in otp_codes(trip_id).items():
        r = client.post(f"/api/trips/{trip_id}/passengers/{eid}/verify-otp", headers=driver_headers, json={"otp": code})
        assert r.status_code == 200, r.text


_extras_counter = __import__("itertools").count(1)


def employee_extras(client, headers, customer_id, code):
    """Employees need a site, a shift and an email. Creates a site and shift for them (as an admin) and returns the fields."""
    n = next(_extras_counter)  # unique names, so the same employee code can be used for several customers
    site = client.post("/api/sites", headers=headers, json={"customer_id": customer_id, "name": f"Site-{code}-{n}", "address": "1 Site Road"})
    shift = client.post("/api/shifts", headers=headers, json={"customer_id": customer_id, "name": f"Shift-{code}-{n}", "start_time": "09:00", "end_time": "17:00"})
    assert site.status_code == 201 and shift.status_code == 201, (site.text, shift.text)
    return dict(site_id=site.json()["id"], shift_id=shift.json()["id"], email=f"{str(code).lower()}.{n}@example.com")


@pytest.fixture(scope="session", autouse=True)
def _migrate():
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture(autouse=True)
def _clean():
    with engine.begin() as c:
        c.execute(text("TRUNCATE expenses, compliance_items, sms_logs, application_settings, trip_status_history, trip_assignments, trip_passengers, trips, shift_definitions, audit_logs, email_logs, password_reset_tokens, users, drivers, vehicles, employees, sites, customers, vendors RESTART IDENTITY CASCADE"))
    auth_service.limiter.reset()


class Outbox:
    def __init__(self):
        self.sent: list[dict] = []
        self.fail = False  # set True to simulate an email provider outage

    def send(self, to, subject, text, html=None, to_name=None):
        if self.fail:
            raise RuntimeError("email provider down")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html, "to_name": to_name})
        return "test-id"


@pytest.fixture(autouse=True)
def outbox(monkeypatch):
    box = Outbox()
    monkeypatch.setattr(email_mod, "get_provider", lambda: box)
    return box


class SmsBox:
    def __init__(self):
        self.sent: list[dict] = []
        self.fail: str | None = None  # set to a message to simulate a provider outage
        self.fail_for: set[str] = set()

    def send(self, to, body, status_callback=None):
        from app.services.sms import SmsError
        if self.fail or to in self.fail_for:
            raise SmsError(self.fail or "Twilio 21211: invalid 'To' number")
        self.sent.append({"to": to, "body": body})
        return f"SM{len(self.sent):032d}"


@pytest.fixture(autouse=True)
def smsbox(monkeypatch):
    from app.services import sms as sms_mod
    box = SmsBox()
    monkeypatch.setattr(sms_mod, "get_provider", lambda: box)
    return box


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


def make_user(db, username, role, vendor_id=None, password=PASSWORD, setup_done=True, **kw):
    u = User(
        first_name=username.title(), last_name="Test", username=username, email=f"{username}@example.com",
        role=role, vendor_id=vendor_id, password_hash=hash_password(password),
        initial_setup_completed_at=auth_service.now() if setup_done else None, **kw,
    )
    db.add(u)
    db.commit()
    return u


def login(client, username, password=PASSWORD):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    return r


def auth(client, username, password=PASSWORD):
    r = login(client, username, password)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def world(db):
    va = Vendor(code="A", name="Alpha")
    vb = Vendor(code="B", name="Bravo")
    db.add_all([va, vb])
    db.commit()
    sa = make_user(db, "root", Role.SUPER_ADMIN)
    adm_a = make_user(db, "admin_a", Role.VENDOR_ADMIN, va.id)
    adm_b = make_user(db, "admin_b", Role.VENDOR_ADMIN, vb.id)
    return dict(va=va, vb=vb, sa=sa, adm_a=adm_a, adm_b=adm_b)
