"""Trip notifications to employees and drivers, over the channels a vendor has enabled (SMS and/or Email).

Flow (spec 2.10):
1. Inside the trip transaction we write `sms_logs` / `email_logs` rows with status 'pending' (the trip is the source of truth).
2. After the transaction commits, `deliver()` runs in the background and sends each row through its provider, recording
   sent/failed. A provider outage never blocks or rolls back a trip.

Channels: Super Admin / Vendor Admin enable SMS and/or Email per vendor (services/app_settings.py). Both on = both used;
one on = only that one; both off = nothing is sent.

Employees' messages carry their drop-off OTP as the token "[OTP]". The stored text (and so every log screen) never holds the
code; `deliver()` swaps in the real code from the passenger's seed only at the moment of sending. Drivers never get an OTP.

Templates are centralised here (spec 16.2); see docs/SMS_TEMPLATES.md for the DLT-registration wording.
"""
import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import to_local
from app.db.session import SessionLocal
from app.models import (
    Customer, Driver, EmailLog, Employee, LookupValue, Site, SmsLog, Trip, TripPassenger, User, Vehicle,
)
from app.core.config import get_settings
from app.services import app_settings, email as mail, email_templates, otp, sms

log = logging.getLogger("yaan.notifications")

EMPTY: tuple[list[int], list[int]] = ([], [])  # (sms log ids, email log ids) still to send

TEMPLATES: dict[str, str] = {
    "trip_created_driver": (
        "YAAN: New trip {code} on {date} at {time}. Customer: {customer} ({site}). "
        "Pickup: {pickup}. Drop: {drop}. Vehicle: {vehicle}. Please open YAAN to accept."),
    "trip_created_employee": (
        "YAAN: Trip {code} booked for {date} at {time}. Pickup: {pickup}. Drop: {drop}. "
        "Driver: {driver_name} ({driver_phone}). Vehicle: {vehicle}. "
        "Your OTP is " + otp.TOKEN + ". Share it with the driver only when you reach your drop point."),
    "trip_cancelled_driver": "YAAN: Trip {code} scheduled for {date} at {time} has been cancelled. No action needed.",
    "trip_cancelled_employee": "YAAN: Your trip {code} scheduled for {date} at {time} has been cancelled.",
    "trip_reassigned_driver": (
        "YAAN: Trip {code} on {date} at {time} is now assigned to you. Pickup: {pickup}. Drop: {drop}. "
        "Vehicle: {vehicle}. Please open YAAN to accept."),
    "trip_unassigned_driver": "YAAN: Trip {code} on {date} at {time} has been reassigned to another driver. No action needed.",
    "trip_reassigned_employee": (
        "YAAN: Update for trip {code} on {date} at {time}. Driver: {driver_name} ({driver_phone}). Vehicle: {vehicle}."),
}
SUBJECTS: dict[str, str] = {
    "trip_created_driver": "New trip {code} assigned to you",
    "trip_created_employee": "Your trip {code} is booked",
    "trip_cancelled_driver": "Trip {code} cancelled",
    "trip_cancelled_employee": "Your trip {code} was cancelled",
    "trip_reassigned_driver": "Trip {code} is now assigned to you",
    "trip_unassigned_driver": "Trip {code} reassigned",
    "trip_reassigned_employee": "Update for your trip {code}",
}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _short(s: str | None, n: int = 90) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def render(template: str, ctx: dict) -> str:
    return TEMPLATES[template].format(**ctx)


def build_context(*, code: str, start: datetime, customer: str, site: str, pickup: str, drop: str,
                  vehicle: str, driver_name: str, driver_phone: str) -> dict:
    local = to_local(start)
    return {"code": code, "date": f"{local:%d %b %Y}", "time": f"{local:%H:%M}", "customer": customer, "site": site,
            "pickup": _short(pickup), "drop": _short(drop), "vehicle": vehicle, "driver_name": driver_name,
            "driver_phone": driver_phone}


def passenger_route(trip_type: str | None, trip: Trip, p: TripPassenger) -> tuple[str, str]:
    """A passenger's own address is their pickup on Pickup trips and their drop on Drop trips; else the trip-level one."""
    pickup = p.address if trip_type == "Pickup" and p.address else trip.pickup_address
    drop = p.address if trip_type == "Drop" and p.address else trip.drop_address
    return pickup, drop


def _load(db: Session, trip: Trip):
    db.flush()  # sessions run with autoflush off; make sure passengers/assignments written so far are visible
    driver, vehicle = db.get(Driver, trip.driver_id), db.get(Vehicle, trip.vehicle_id)
    customer, site = db.get(Customer, trip.customer_id), db.get(Site, trip.site_id)
    ttype = db.scalar(select(LookupValue.label).where(LookupValue.id == trip.trip_type_id))
    pax = list(db.scalars(select(TripPassenger).where(TripPassenger.trip_id == trip.id).order_by(TripPassenger.sequence)))
    return driver, vehicle, customer, site, ttype, pax


def _ctx(trip: Trip, driver: Driver, vehicle: Vehicle, customer: Customer, site: Site, pickup=None, drop=None) -> dict:
    return build_context(code=trip.code or "", start=trip.scheduled_start, customer=customer.name, site=site.name,
                         pickup=pickup or trip.pickup_address, drop=drop or trip.drop_address,
                         vehicle=vehicle.vehicle_number, driver_name=f"{driver.first_name} {driver.last_name}",
                         driver_phone=driver.contact_number)


def driver_email(db: Session, driver: Driver) -> str | None:
    """The driver's own email if set, else the email of the login linked to them."""
    return driver.email or db.scalar(select(User.email).where(User.driver_id == driver.id))


class _Batch:
    """Collects the rows created for one trip event, for the channels the vendor has on."""

    def __init__(self, db: Session, trip: Trip):
        self.db, self.trip = db, trip
        self.sms_on, self.email_on = app_settings.channels(db, trip.vendor_id)
        self.sms_rows: list[SmsLog] = []
        self.email_rows: list[EmailLog] = []

    @property
    def active(self) -> bool:
        return self.sms_on or self.email_on

    def add(self, rtype: str, template: str, name: str, phone: str | None, email: str | None, ctx: dict,
            driver_id: int | None = None, employee_id: int | None = None) -> None:
        text = render(template, ctx)
        if self.sms_on:
            norm = sms.normalize_phone(phone)
            row = SmsLog(vendor_id=self.trip.vendor_id, trip_id=self.trip.id, recipient_type=rtype, driver_id=driver_id,
                         employee_id=employee_id, recipient_name=name, phone=norm or (phone or "")[:32],
                         template=template, body=text)
            if norm is None:  # recorded, but there is nothing to send to
                row.status, row.failure_reason = "failed", "Invalid or missing phone number"
            self.db.add(row)
            self.sms_rows.append(row)
        if self.email_on:
            ok = bool(email and _EMAIL.match(email.strip()))
            row = EmailLog(vendor_id=self.trip.vendor_id, trip_id=self.trip.id, recipient_type=rtype, driver_id=driver_id,
                           employee_id=employee_id, recipient_name=name, to_email=(email or "(none)").strip()[:254],
                           template=template, subject=SUBJECTS[template].format(**ctx), body=text,
                           status="pending" if ok else "failed")
            if not ok:
                row.failure_reason = "No valid email address on file"
            self.db.add(row)
            self.email_rows.append(row)

    def finish(self) -> tuple[list[int], list[int]]:
        self.db.flush()
        return ([r.id for r in self.sms_rows if r.status == "pending"],
                [r.id for r in self.email_rows if r.status == "pending"])


# ---------------------------------------------------------------- queueing (inside the caller's transaction)
def queue_trip_created(db: Session, trip: Trip, only_employee_ids: set[int] | None = None) -> tuple[list[int], list[int]]:
    """The 'final trip' notification: driver + every employee (or just `only_employee_ids`, for late additions)."""
    b = _Batch(db, trip)
    if not b.active:
        return EMPTY
    driver, vehicle, customer, site, ttype, pax = _load(db, trip)
    if only_employee_ids is None:
        b.add("driver", "trip_created_driver", f"{driver.first_name} {driver.last_name}", driver.contact_number,
              driver_email(db, driver), _ctx(trip, driver, vehicle, customer, site), driver_id=driver.id)
    for p in pax:
        if only_employee_ids is not None and p.employee_id not in only_employee_ids:
            continue
        pu, dr = passenger_route(ttype, trip, p)
        emp = db.get(Employee, p.employee_id)
        b.add("employee", "trip_created_employee", p.name, p.mobile, emp.email if emp else None,
              _ctx(trip, driver, vehicle, customer, site, pu, dr), employee_id=p.employee_id)
    return b.finish()


def queue_trip_cancelled(db: Session, trip: Trip) -> tuple[list[int], list[int]]:
    if trip.driver_id is None:  # a request that was never assigned: nobody was told about it, so nobody needs telling
        return EMPTY
    if not app_settings.get_bool(db, "sms_on_cancellation", trip.vendor_id):
        return EMPTY
    b = _Batch(db, trip)
    if not b.active:
        return EMPTY
    driver, vehicle, customer, site, _t, pax = _load(db, trip)
    ctx = _ctx(trip, driver, vehicle, customer, site)
    b.add("driver", "trip_cancelled_driver", f"{driver.first_name} {driver.last_name}", driver.contact_number,
          driver_email(db, driver), ctx, driver_id=driver.id)
    for p in pax:
        emp = db.get(Employee, p.employee_id)
        b.add("employee", "trip_cancelled_employee", p.name, p.mobile, emp.email if emp else None, ctx, employee_id=p.employee_id)
    return b.finish()


def queue_trip_reassigned(db: Session, trip: Trip, old_driver_id: int, driver_changed: bool) -> tuple[list[int], list[int]]:
    if not app_settings.get_bool(db, "sms_on_reassignment", trip.vendor_id):
        return EMPTY
    b = _Batch(db, trip)
    if not b.active:
        return EMPTY
    driver, vehicle, customer, site, ttype, pax = _load(db, trip)
    if driver_changed:
        old = db.get(Driver, old_driver_id)
        b.add("driver", "trip_unassigned_driver", f"{old.first_name} {old.last_name}", old.contact_number,
              driver_email(db, old), _ctx(trip, old, vehicle, customer, site), driver_id=old.id)
        b.add("driver", "trip_reassigned_driver", f"{driver.first_name} {driver.last_name}", driver.contact_number,
              driver_email(db, driver), _ctx(trip, driver, vehicle, customer, site), driver_id=driver.id)
    for p in pax:
        pu, dr = passenger_route(ttype, trip, p)
        emp = db.get(Employee, p.employee_id)
        b.add("employee", "trip_reassigned_employee", p.name, p.mobile, emp.email if emp else None,
              _ctx(trip, driver, vehicle, customer, site, pu, dr), employee_id=p.employee_id)
    return b.finish()


# ---------------------------------------------------------------- delivery (after commit, own session)
def _seed(db: Session, trip_id: int | None, employee_id: int | None) -> str | None:
    if trip_id is None or employee_id is None:
        return None
    return db.scalar(select(TripPassenger.otp_seed).where(TripPassenger.trip_id == trip_id, TripPassenger.employee_id == employee_id))


def _email_content(db: Session, row: EmailLog) -> tuple[str, str | None]:
    """(plain text, html) for a queued trip email. Built from the trip as it is now, with full (not SMS-shortened) addresses and the
    real OTP for employees. If anything is missing we fall back to the stored plain text, so a notification is never lost."""
    code = None
    stored = row.body or ""
    seed = _seed(db, row.trip_id, row.employee_id)
    fallback = otp.reveal(stored, seed, row.trip_id, row.employee_id)
    if otp.TOKEN in stored and seed and row.trip_id is not None and row.employee_id is not None:
        code = otp.code(seed, row.trip_id, row.employee_id)
    try:
        trip = db.get(Trip, row.trip_id)
        driver, vehicle, customer, site, ttype, pax = _load(db, trip)
        if row.recipient_type == "driver" and row.driver_id:
            driver = db.get(Driver, row.driver_id) or driver  # e.g. the driver who was just replaced
        pickup, drop = trip.pickup_address, trip.drop_address
        mine = next((p for p in pax if p.employee_id == row.employee_id), None)
        if mine is not None:
            pickup, drop = passenger_route(ttype, trip, mine)
        local = to_local(trip.scheduled_start)
        ctx = {"code": trip.code or "", "date": f"{local:%d %b %Y}", "time": f"{local:%H:%M}", "customer": customer.name, "site": site.name,
               "trip_type": ttype or "", "pickup": " ".join((pickup or "").split()), "drop": " ".join((drop or "").split()),
               "vehicle": vehicle.vehicle_number, "driver_name": f"{driver.first_name} {driver.last_name}",
               "driver_phone": driver.contact_number}
        return email_templates.trip(row.template, row.recipient_name or "there", ctx, code, get_settings().frontend_url)
    except Exception:  # noqa: BLE001 - formatting must never block delivery
        log.exception("Could not format email %s; sending plain text", row.id)
        return fallback, None


def deliver(pending: tuple[list[int], list[int]]) -> None:
    sms_ids, email_ids = pending
    if not sms_ids and not email_ids:
        return
    with SessionLocal() as db:
        if sms_ids:
            provider, callback = sms.get_provider(), sms.status_callback_url()
            for lid in sms_ids:
                row = db.get(SmsLog, lid)
                if row is None or row.status not in ("pending", "failed"):
                    continue
                row.attempts += 1
                try:
                    text = otp.reveal(row.body, _seed(db, row.trip_id, row.employee_id), row.trip_id, row.employee_id)
                    row.provider_message_id = provider.send(row.phone, text, callback)
                    row.status, row.failure_reason = "sent", None
                    row.sent_at = datetime.now(timezone.utc)
                except Exception as exc:  # noqa: BLE001 - provider problems are recorded, never raised
                    row.status, row.failure_reason = "failed", str(exc)[:480]
                    log.warning("SMS %s failed: %s", lid, exc)
                db.commit()
        if email_ids:
            email_provider = mail.get_provider()
            for eid in email_ids:
                row = db.get(EmailLog, eid)
                if row is None or row.status not in ("pending", "failed"):
                    continue
                row.attempts += 1
                try:
                    text, html = _email_content(db, row)
                    row.provider_message_id = email_provider.send(row.to_email, row.subject or "YAAN trip", text, html,
                                                                  to_name=row.recipient_name)
                    row.status, row.failure_reason = "sent", None
                    row.sent_at = datetime.now(timezone.utc)
                except Exception as exc:  # noqa: BLE001
                    row.status, row.failure_reason = "failed", str(exc)[:480]
                    log.warning("Email %s failed: %s", eid, exc)
                db.commit()


def mark_for_retry(db: Session, row: SmsLog | EmailLog) -> None:
    row.status, row.failure_reason = "pending", None
