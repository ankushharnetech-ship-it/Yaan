"""DEVELOPMENT-ONLY demo data (spec 31).   python -m app.seed_demo

Builds everything through the real API (so every business rule is enforced), as the Super Admin / Vendor Admin /
Operators / Drivers it creates. SMS and email are forced to the console - nothing is ever sent for real.
All demo accounts share one publicly-known password; never run this against production.
"""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.security import hash_password
from app.core.timeutil import tz
from app.db.session import SessionLocal
from app.models import Customer, LookupValue, Trip, User, Vendor
from app.seed import DEV_PASSWORD
from app.seed import main as seed_base
from app.services import email as email_mod, sms as sms_mod
from app.services.auth_service import now

FIRST = ["Aarav", "Diya", "Vivaan", "Anaya", "Aditya", "Isha", "Kabir", "Meera", "Rohan", "Saanvi", "Arjun", "Kiara"]
LAST = ["Sharma", "Patel", "Iyer", "Nair", "Gupta", "Reddy", "Singh", "Das", "Joshi", "Kulkarni"]
CITIES = [("Pune", "18.52,73.85"), ("Mumbai", "19.07,72.87")]
CAPACITIES = [3, 4, 6, 7, 12]


def run() -> None:
    cfg = get_settings()
    if cfg.environment != "development":
        raise SystemExit("Refusing to seed demo data: ENVIRONMENT is not 'development'")
    # Safety first: demo phone numbers/emails are fake - route everything to the console.
    sms_mod.get_provider = lambda: sms_mod.ConsoleSmsProvider()
    email_mod.get_provider = lambda: email_mod.ConsoleEmailProvider()
    seed_base()

    from app.main import app  # imported late so the patches above are in place
    client = TestClient(app)

    def login(username: str) -> dict:
        r = client.post("/api/auth/login", json={"username": username, "password": DEV_PASSWORD})
        assert r.status_code == 200, f"login {username}: {r.text}"
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    def call(method: str, path: str, h: dict, **kw):
        r = client.request(method, f"/api{path}", headers=h, **kw)
        assert r.status_code < 300, f"{method} {path}: {r.status_code} {r.text}"
        return r.json() if r.content else None

    def at(day: int, hour: int, minute: int = 0, plus: int = 0) -> str:
        d = datetime.now(tz()).date() + timedelta(days=day)
        return (datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz()) + timedelta(minutes=plus)).astimezone(timezone.utc).isoformat()

    def make_user(sa: dict, vendor_id: int, username: str, role: str, first: str, last: str, driver_id: int | None = None, customer_id: int | None = None):
        call("POST", "/users", sa, json=dict(first_name=first, last_name=last, username=username, email=f"{username}@example.com",
                                              role=role, vendor_id=vendor_id, driver_id=driver_id, customer_id=customer_id, mobile="9000000000", address="1 Demo Street, Pune"))
        with SessionLocal() as db:  # demo logins are usable immediately (no temp-password step)
            db.execute(update(User).where(User.username == username).values(
                password_hash=hash_password(DEV_PASSWORD), initial_setup_completed_at=now(), temp_password_expires_at=None))
            db.commit()

    sa = login("superadmin")
    with SessionLocal() as db:
        lk = {(r.category, r.label): r.id for r in db.scalars(select(LookupValue))}
        vendors = {v.code: v.id for v in db.scalars(select(Vendor))}
        already = {c.vendor_id for c in db.scalars(select(Customer))}

    creds = [("superadmin", "Super Admin", "-")]
    for vi, (code, tag) in enumerate((("VND-A", "alpha"), ("VND-B", "bravo"))):
        vid = vendors[code]
        if vid in already:
            print(f"{code}: demo data already present - skipped")
            continue
        n = vi * 100  # keeps phone numbers/plates unique per vendor

        # --- people & fleet
        make_user(sa, vid, f"admin_{tag}", "vendor_admin", "Vendor", f"Admin {tag.title()}")
        adm = login(f"admin_{tag}")
        drivers = []
        for k in range(1, 6):
            drivers.append(call("POST", "/drivers", adm, json=dict(
                first_name=FIRST[(k + vi) % 12], last_name=LAST[k], contact_number=f"9{vi}00000{k:03d}", gender="male" if k % 4 else "female",
                license_type_id=lk[("license_type", "LMV - Transport")], license_number=f"{tag[:2].upper()}-DL-{k:04d}",
                experience_months=12 * k, email=f"driver{tag}{k}@example.com", date_of_joining="2023-01-01", emergency_contact="9100000000", home_address=f"{k} Demo Lane, Pune", languages=["English", "Hindi"], rest_days=["Sun"])))
            make_user(sa, vid, f"drv_{tag}{k}", "driver", drivers[-1]["first_name"], drivers[-1]["last_name"], drivers[-1]["id"]) if k <= 3 else None
        vehicles = []
        for k, cap in enumerate(CAPACITIES, 1):
            vtype = "Sedan" if cap <= 4 else "MUV" if cap <= 7 else "Mini Bus"
            vehicles.append(call("POST", "/vehicles", adm, json=dict(
                vehicle_number=f"MH{12 + vi}AB{n + k:04d}", vehicle_code=f"{tag[:2].upper()}-V{k}", vehicle_type_id=lk[("vehicle_type", vtype)],
                model=["Dzire", "Etios", "Ertiga", "Innova", "Traveller"][k - 1], capacity=cap, fuel_type_id=lk[("fuel_type", "Diesel")])))

        # --- customers, sites, shifts, employees
        employees: dict[int, list] = {}
        customers = []
        for ci, cname in enumerate((f"{tag.title()} Tech Park", f"{tag.title()} Finance Hub"), 1):
            lat, lng = (float(x) for x in CITIES[ci % 2][1].split(","))
            cust = call("POST", "/customers", adm, json=dict(code=f"{tag[:2].upper()}C{ci}", name=cname, contact_person="Front Desk", email=f"desk.{tag}{ci}@example.com", phone="9999999999",
                                                              address=f"{ci}0{ci} Business Bay, {CITIES[ci % 2][0]}", latitude=lat, longitude=lng))
            customers.append(cust)
            sites = [call("POST", "/sites", adm, json=dict(customer_id=cust["id"], name=f"{city} Office", address=f"{ci} Main Road, {city}",
                                                            city=city, latitude=float(ll.split(",")[0]), longitude=float(ll.split(",")[1])))
                     for city, ll in CITIES]
            shift = call("POST", "/shifts", adm, json=dict(customer_id=cust["id"], name="Morning", start_time="06:00", end_time="14:00"))
            call("POST", "/shifts", adm, json=dict(customer_id=cust["id"], name="Night", start_time="22:00", end_time="06:00"))
            employees[cust["id"]] = [call("POST", "/employees", adm, json=dict(
                customer_id=cust["id"], site_id=sites[0]["id"], shift_id=shift["id"], email=f"emp{vi}{ci}{e:02d}@example.com", employee_code=f"E{ci}{e:03d}", first_name=FIRST[e % 12], last_name=LAST[(e + ci) % 10],
                mobile=f"98{vi}{ci}00{e:04d}", gender="female" if e % 3 == 0 else "male", department="Operations",
                address=f"{e} Residency Lane, {CITIES[0][0]}",
                latitude=round(18.50 + e * 0.004, 5), longitude=round(73.80 + e * 0.004, 5)))
                for e in range(1, 11)]

        # Operators work for one customer company: both of this vendor's operators serve the first customer
        for k in (1, 2):
            make_user(sa, vid, f"ops_{tag}{k}", "operator", f"Operator{k}", tag.title(), customer_id=customers[0]["id"])

        # --- compliance (a spread of valid / about-to-expire / expired)
        today = datetime.now(tz()).date()
        for i, d in enumerate(drivers):
            call("POST", "/compliance/items", adm, json=dict(subject_type="driver", driver_id=d["id"], doc_type_id=lk[("driver_doc_type", "Driving licence")],
                                                              reference_number=d["license_number"], expiry_date=(today + timedelta(days=[400, 20, -10, 200, 45][i])).isoformat()))
        for i, v in enumerate(vehicles):
            call("POST", "/compliance/items", adm, json=dict(subject_type="vehicle", vehicle_id=v["id"], doc_type_id=lk[("vehicle_doc_type", "Insurance")],
                                                              expiry_date=(today + timedelta(days=[300, 12, 90, -3, 250][i])).isoformat()))

        # --- trips in every lifecycle state, booked by an operator
        op = login(f"ops_{tag}1")
        cust, emps = customers[0], employees[customers[0]["id"]]
        site = call("GET", f"/sites?customer_id={cust['id']}", op)["items"][0]
        ttype = lk[("trip_type", "Pickup")]
        men = [e for e in emps if e["gender"] == "male"]
        women = [e for e in emps if e["gender"] == "female"]

        def request(day, hour, mins, who):
            """The Operator's step: employees only, no driver or vehicle."""
            return call("POST", "/trips", op, json=dict(
                customer_id=cust["id"], site_id=site["id"], trip_type_id=ttype, scheduled_start=at(day, hour), scheduled_end=at(day, hour, plus=mins),
                pickup_address=who[0]["address"], drop_address=site["address"], employee_ids=[e["id"] for e in who], route_name="Demo route"))

        def book(day, hour, mins, who, driver, vehicle):
            """Operator requests, then the Vendor Admin assigns (this is when the driver and employees get their SMS)."""
            t = request(day, hour, mins, who)
            return call("POST", f"/trips/{t['id']}/assign", adm, json={"driver_id": driver["id"], "vehicle_id": vehicle["id"]})

        def drive(trip, driver_no, *steps):
            dh = login(f"drv_{tag}{driver_no}")
            for s in steps:
                if s == "completed":  # every employee must give the driver their OTP first; the requesting Operator can read them
                    for p in call("GET", f"/trips/{trip['id']}", op)["passengers"]:
                        call("POST", f"/trips/{trip['id']}/passengers/{p['employee_id']}/verify-otp", dh, json={"otp": p["otp"]})
                call("POST", f"/trips/{trip['id']}/status", dh, json={"status": s})

        done = book(-1, 8, 60, men[:2], drivers[0], vehicles[1])                      # completed (yesterday)
        drive(done, 1, "accepted", "started", "completed")
        ongoing = book(0, max(0, datetime.now(tz()).hour - 1), 120, men[2:4], drivers[1], vehicles[2])   # in progress now
        drive(ongoing, 2, "accepted", "started")
        accepted = book(0, 18, 60, women[:1] + men[4:5], drivers[2], vehicles[3])     # accepted, includes a woman => escort seat
        drive(accepted, 3, "accepted")
        book(1, 9, 60, women[1:3] + men[5:6], drivers[3], vehicles[1])                # assigned (tomorrow), escort seat reserved
        book(1, 22, 90, men[:3], drivers[4], vehicles[4])                            # assigned, night shift
        gone = book(0, 20, 60, men[:1], drivers[0], vehicles[0])
        call("POST", f"/trips/{gone['id']}/cancel", adm, json={"reason": "Demo: employee on leave"})   # cancelled (assigned trips: admin only)
        # requests still waiting for the Vendor Admin to assign a driver and vehicle
        request(1, 7, 60, women[:1] + men[:1])                                        # awaiting assignment (includes a woman => 3 seats needed)
        request(2, 18, 90, men[1:4])                                                  # awaiting assignment
        rejected = request(2, 6, 60, men[4:5])
        call("POST", f"/trips/{rejected['id']}/cancel", adm, json={"reason": "Demo: no vehicle free at that hour"})   # rejected request

        # --- expenses entered by different roles (each person's name is stored with the entry)
        def spend(who: dict, cat: str, amount: str, days_ago: int, pay: str, veh=None, note=None, drv=None):
            call("POST", "/expenses", who, json=dict(
                expense_date=(datetime.now(tz()).date() - timedelta(days=days_ago)).isoformat(), category_id=lk[("expense_category", cat)],
                amount=amount, payment_method=pay, vehicle_id=veh["id"] if veh else None, driver_id=drv["id"] if drv else None, description=note))
        d1 = login(f"drv_{tag}1")
        spend(d1, "Fuel", "2850.00", 1, "fuel_card", vehicles[1], "Diesel fill-up, 38 L")
        spend(d1, "Toll & parking", "180.00", 2, "upi", vehicles[1], "Expressway toll")
        spend(op, "Cleaning", "400.00", 3, "cash", vehicles[2], "Interior cleaning")
        spend(adm, "Maintenance & repair", "7600.00", 5, "bank_transfer", vehicles[3], "Brake pads and service", drivers[2])
        spend(adm, "Insurance", "21400.00", 12, "bank_transfer", vehicles[4], "Annual premium")
        spend(adm, "Fuel", "3100.00", 40, "card", vehicles[0], "Fuel last month")

        with SessionLocal() as db:  # make history look real: completed/started stamps follow the schedule
            for t in db.scalars(select(Trip).where(Trip.vendor_id == vid)):
                if t.status.value == "completed":
                    t.started_at, t.completed_at = t.scheduled_start + timedelta(minutes=3), t.scheduled_end - timedelta(minutes=5)
                elif t.status.value == "started":
                    t.started_at = t.scheduled_start + timedelta(minutes=2)
            db.commit()

        creds += [(f"admin_{tag}", "Vendor Admin", code), (f"ops_{tag}1 / ops_{tag}2", "Operator", code), (f"drv_{tag}1 .. drv_{tag}3", "Driver", code)]
        print(f"{code}: 1 admin, 2 operators, 5 drivers, 5 vehicles, 2 customers, 20 employees, 9 trips (2 awaiting assignment), compliance records, 6 expenses")

    print("\nDEMO LOGINS  (development only - password for all:", DEV_PASSWORD + ")")
    for u, role, v in creds:
        print(f"  {u:<28} {role:<13} {v}")
    print("\nTry to book a clash on purpose to see the guards: e.g. put drivers[0] on a second trip within 30 min of one of "
          "today's trips, or load 4 people (3 men + 1 woman) into the 3-seat vehicle.")


if __name__ == "__main__":
    run()
