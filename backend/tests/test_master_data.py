import pytest
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import LookupValue, Role, User
from tests.conftest import CONTACT, GEO, VENDOR, auth, employee_extras, make_user


@pytest.fixture
def lk(db):
    out: dict[str, dict[str, int]] = {}
    for r in db.scalars(select(LookupValue)):
        out.setdefault(r.category, {})[r.label] = r.id
    return out


@pytest.fixture
def hs(client, world, db):
    make_user(db, "oper_a", Role.OPERATOR, world["va"].id)
    make_user(db, "drv_a", Role.DRIVER, world["va"].id)
    headers = {n: auth(client, n) for n in ("root", "admin_a", "admin_b", "oper_a", "drv_a")}
    _ADMIN["h"] = headers["admin_a"]
    return headers


_ADMIN: dict = {}  # set by the hs fixture: the Vendor Admin who creates the site/shift an employee needs


def mk_customer(client, h, code="C1", **kw):
    r = client.post("/api/customers", headers=h, json={"code": code, "name": f"Customer {code}", **GEO, **CONTACT, **kw})
    assert r.status_code == 201, r.text
    with SessionLocal() as s:  # the Operator works for the first customer created in a test
        op = s.scalar(select(User).where(User.username == "oper_a"))
        if op and op.customer_id is None and op.vendor_id == r.json()["vendor_id"]:
            op.customer_id = r.json()["id"]
            s.commit()
    return r.json()


def mk_driver(client, h, lk, lic="DL-001", **kw):
    body = dict(first_name="Dev", last_name="Driver", contact_number="+919800000001", gender="male",
                license_type_id=lk["license_type"]["LMV"], license_number=lic, email="d@example.com", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road")
    body.update(kw)
    return client.post("/api/drivers", headers=h, json=body)


def mk_vehicle(client, h, lk, num="MH12AB1234", code="V1", cap=4, **kw):
    body = dict(vehicle_number=num, vehicle_code=code, vehicle_type_id=lk["vehicle_type"]["Sedan"],
                model="Dzire", capacity=cap)
    body.update(kw)
    return client.post("/api/vehicles", headers=h, json=body)


# ---------- lookups / vendors ----------
def test_lookups_seeded(client, hs):
    data = client.get("/api/lookups", headers=hs["admin_a"]).json()
    assert {"vehicle_type", "fuel_type", "license_type", "induction_type", "trip_type"} <= set(data)
    assert "Tempo Traveller" in [v["label"] for v in data["vehicle_type"]]


def test_vendor_management_rules(client, hs, world):
    r = client.post("/api/vendors", headers=hs["root"], json={"name": "Charlie", "code": "C", **VENDOR})
    assert r.status_code == 201
    vid = r.json()["id"]
    dup = client.post("/api/vendors", headers=hs["root"], json={"name": "X", "code": "c", **VENDOR})
    assert dup.status_code == 422 and dup.json()["detail"][0]["loc"][-1] == "code"
    assert client.patch(f"/api/vendors/{vid}/status", headers=hs["root"], json={"status": "inactive"}).json()["status"] == "inactive"
    # vendor admin: sees only own vendor, cannot edit
    items = client.get("/api/vendors", headers=hs["admin_a"]).json()["items"]
    assert [v["code"] for v in items] == ["A"]
    assert client.get(f"/api/vendors/{world['vb'].id}", headers=hs["admin_a"]).status_code == 404
    assert client.put(f"/api/vendors/{world['va'].id}", headers=hs["admin_a"], json={"name": "n", "code": "A", **VENDOR}).status_code == 403
    assert client.get("/api/vendors", headers=hs["oper_a"]).status_code == 403


# ---------- customers & sites ----------
def test_customer_is_pinned_to_vendor_admin_vendor(client, hs, world):
    c = mk_customer(client, hs["admin_a"], vendor_id=world["vb"].id)  # attempt to spoof vendor
    assert c["vendor_id"] == world["va"].id


def test_super_admin_must_choose_vendor(client, hs, world):
    r = client.post("/api/customers", headers=hs["root"], json={"code": "Z", "name": "Z", **GEO, **CONTACT})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "vendor_id"
    ok = client.post("/api/customers", headers=hs["root"], json={"code": "Z", "name": "Z", "vendor_id": world["vb"].id, **GEO, **CONTACT})
    assert ok.status_code == 201


def test_customer_with_multiple_sites(client, hs):
    c = mk_customer(client, hs["admin_a"])
    for name, city in (("HQ", "Pune"), ("Tech Park", "Mumbai"), ("Warehouse", "Nashik")):
        r = client.post("/api/sites", headers=hs["admin_a"], json={
            "customer_id": c["id"], "name": name, "address": f"{name} road", "city": city})
        assert r.status_code == 201, r.text
    dup = client.post("/api/sites", headers=hs["admin_a"], json={"customer_id": c["id"], "name": "hq", "address": "x"})
    assert dup.status_code == 422
    sites = client.get(f"/api/sites?customer_id={c['id']}", headers=hs["oper_a"]).json()
    assert sites["total"] == 3
    assert client.get(f"/api/customers/{c['id']}", headers=hs["admin_a"]).json()["site_count"] == 3


def test_customer_vendor_isolation(client, hs):
    c = mk_customer(client, hs["admin_a"])
    assert client.get(f"/api/customers/{c['id']}", headers=hs["admin_b"]).status_code == 404
    assert client.put(f"/api/customers/{c['id']}", headers=hs["admin_b"], json={"code": "C1", "name": "hax", **GEO, **CONTACT}).status_code == 404
    assert client.get("/api/customers", headers=hs["admin_b"]).json()["total"] == 0
    assert client.post("/api/sites", headers=hs["admin_b"],
                       json={"customer_id": c["id"], "name": "S", "address": "a"}).status_code == 404


def test_operator_reads_but_cannot_write_master_data(client, hs, lk):
    c = mk_customer(client, hs["admin_a"])
    assert client.get("/api/customers", headers=hs["oper_a"]).json()["total"] == 1
    assert client.post("/api/customers", headers=hs["oper_a"], json={"code": "N", "name": "N", **GEO, **CONTACT}).status_code == 403
    assert client.post("/api/sites", headers=hs["oper_a"], json={"customer_id": c["id"], "name": "S", "address": "a"}).status_code == 403
    assert client.patch(f"/api/customers/{c['id']}/status", headers=hs["oper_a"], json={"status": "inactive"}).status_code == 403
    assert mk_driver(client, hs["oper_a"], lk).status_code == 403
    assert mk_vehicle(client, hs["oper_a"], lk).status_code == 403


# ---------- employees ----------
def mk_employee(client, h, customer_id, code="E1", **kw):
    body = dict(customer_id=customer_id, employee_code=code, first_name="Asha", last_name="Rao",
                mobile="9876543210", gender="female", **GEO)
    if not {"site_id", "shift_id", "email"} <= kw.keys():  # prerequisites are created for the customer's own vendor admin
        body.update({k: v for k, v in employee_extras(client, _ADMIN["h"], customer_id, code).items() if k not in kw})
    body.update(kw)
    return client.post("/api/employees", headers=h, json=body)


def test_employee_rules(client, hs):
    c1, c2 = mk_customer(client, hs["admin_a"], "C1"), mk_customer(client, hs["admin_a"], "C2")
    s1 = client.post("/api/sites", headers=hs["admin_a"], json={"customer_id": c1["id"], "name": "S", "address": "a"}).json()

    assert mk_employee(client, hs["admin_a"], c1["id"], mobile=None).status_code == 422
    assert mk_employee(client, hs["admin_a"], c1["id"], mobile="abc").status_code == 422
    assert mk_employee(client, hs["admin_a"], c1["id"], gender=None).status_code == 422

    ok = mk_employee(client, hs["admin_a"], c1["id"], site_id=s1["id"])
    assert ok.status_code == 201 and ok.json()["site_name"] == "S"
    # code unique within a customer, reusable across customers
    assert mk_employee(client, hs["admin_a"], c1["id"]).status_code == 422
    assert mk_employee(client, hs["admin_a"], c2["id"]).status_code == 201
    # a site of another customer is rejected
    bad = mk_employee(client, hs["admin_a"], c2["id"], code="E9", site_id=s1["id"])
    assert bad.status_code == 422 and bad.json()["detail"][0]["loc"][-1] == "site_id"

    # customer cannot be changed on update
    eid = ok.json()["id"]
    body = {k: ok.json()[k] for k in ("employee_code", "first_name", "last_name", "mobile", "gender", "address", "latitude", "longitude", "site_id", "shift_id", "email")}
    assert client.put(f"/api/employees/{eid}", headers=hs["admin_a"], json={**body, "customer_id": c2["id"]}).status_code == 422
    assert client.put(f"/api/employees/{eid}", headers=hs["admin_a"], json={**body, "first_name": "Asha2"}).json()["first_name"] == "Asha2"


def test_employee_address_latitude_and_longitude_are_mandatory(client, hs):
    c = mk_customer(client, hs["admin_a"])
    ok = mk_employee(client, hs["admin_a"], c["id"], code="GEO1", address="9 Hill Rd, Pune", latitude=18.5204, longitude=73.8567)
    assert ok.status_code == 201 and ok.json()["address"] == "9 Hill Rd, Pune"
    assert ok.json()["latitude"] == 18.5204 and ok.json()["longitude"] == 73.8567
    # every one of the three is required – missing, null and blank are all refused, and the error names the field
    for field in ("address", "latitude", "longitude"):
        for missing in (None, ""):
            body = dict(customer_id=c["id"], employee_code=f"M-{field}", first_name="A", last_name="B", mobile="9876543210", gender="male", **GEO, **employee_extras(client, hs["admin_a"], c["id"], f"M-{field}"))
            body[field] = missing
            r = client.post("/api/employees", headers=hs["admin_a"], json=body)
            assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, (field, missing)
        gone = dict(customer_id=c["id"], employee_code=f"G-{field}", first_name="A", last_name="B", mobile="9876543210", gender="male", **GEO, **employee_extras(client, hs["admin_a"], c["id"], f"G-{field}"))
        del gone[field]
        r = client.post("/api/employees", headers=hs["admin_a"], json=gone)
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, field
    assert mk_employee(client, hs["admin_a"], c["id"], code="WS", address="   ").status_code == 422        # whitespace is not an address
    # ranges
    for bad in ({"latitude": 91}, {"latitude": -91}, {"longitude": 181}, {"longitude": -181}, {"latitude": "north"}):
        r = mk_employee(client, hs["admin_a"], c["id"], code="GEO3", **bad)
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == next(iter(bad)), bad
    assert mk_employee(client, hs["admin_a"], c["id"], code="EDGE", latitude=-90, longitude=180).status_code == 201   # limits are inclusive
    assert mk_employee(client, hs["admin_a"], c["id"], code="ZERO", latitude=0, longitude=0).status_code == 201        # 0 is a real value
    # updates are held to the same rule, for admins and operators alike
    eid = ok.json()["id"]
    body = {k: ok.json()[k] for k in ("employee_code", "first_name", "last_name", "mobile", "gender", "address", "latitude", "longitude", "site_id", "shift_id", "email")}
    moved = client.put(f"/api/employees/{eid}", headers=hs["oper_a"], json={**body, "latitude": 19.076, "longitude": 72.8777})
    assert moved.status_code == 200 and (moved.json()["latitude"], moved.json()["longitude"]) == (19.076, 72.8777)
    for field in ("address", "latitude", "longitude"):
        cleared = client.put(f"/api/employees/{eid}", headers=hs["admin_a"], json={**body, field: None})
        assert cleared.status_code == 422 and cleared.json()["detail"][0]["loc"][-1] == field, field


def test_customer_address_latitude_and_longitude_are_mandatory(client, hs, world):
    ok = client.post("/api/customers", headers=hs["admin_a"], json={"code": "G1", "name": "Geo Co", "address": "5 Tech Park, Pune", "latitude": 18.59, "longitude": 73.74, **CONTACT})
    assert ok.status_code == 201
    assert (ok.json()["address"], ok.json()["latitude"], ok.json()["longitude"]) == ("5 Tech Park, Pune", 18.59, 73.74)
    for field in ("address", "latitude", "longitude"):
        for missing in (None, ""):
            body = {"code": f"M{field[:3]}", "name": "X", **GEO, **CONTACT}
            body[field] = missing
            r = client.post("/api/customers", headers=hs["admin_a"], json=body)
            assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, (field, missing)
        gone = {"code": f"G{field[:3]}", "name": "X", **GEO, **CONTACT}
        del gone[field]
        assert client.post("/api/customers", headers=hs["admin_a"], json=gone).json()["detail"][0]["loc"][-1] == field
    for bad in ({"latitude": 90.5}, {"latitude": -90.5}, {"longitude": 180.5}, {"longitude": -180.5}):
        r = client.post("/api/customers", headers=hs["admin_a"], json={"code": "RNG", "name": "X", **GEO, **CONTACT, **bad})
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == next(iter(bad)), bad
    # Super Admin too (and must still name a vendor)
    sa = client.post("/api/customers", headers=hs["root"], json={"code": "SA1", "name": "SA Co", "vendor_id": world["vb"].id, **GEO, **CONTACT})
    assert sa.status_code == 201
    assert client.post("/api/customers", headers=hs["root"], json={"code": "SA2", "name": "SA Co", "vendor_id": world["vb"].id, "address": "x", **CONTACT}).status_code == 422
    # updates keep the rule
    cid = ok.json()["id"]
    full = {"code": "G1", "name": "Geo Co", "address": "5 Tech Park, Pune", "latitude": 18.59, "longitude": 73.74, **CONTACT}
    assert client.put(f"/api/customers/{cid}", headers=hs["admin_a"], json={**full, "latitude": 19.0}).json()["latitude"] == 19.0
    for field in ("address", "latitude", "longitude"):
        r = client.put(f"/api/customers/{cid}", headers=hs["admin_a"], json={**full, field: None})
        assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == field, field
    # operators still cannot create customers
    assert client.post("/api/customers", headers=hs["oper_a"], json={"code": "OP", "name": "Op Co", **GEO, **CONTACT}).status_code == 403


def test_employee_isolation_and_operator_read(client, hs):
    c = mk_customer(client, hs["admin_a"])
    e = mk_employee(client, hs["admin_a"], c["id"]).json()
    assert client.get(f"/api/employees/{e['id']}", headers=hs["admin_b"]).status_code == 404
    assert client.get("/api/employees", headers=hs["admin_b"]).json()["total"] == 0
    assert client.get("/api/employees", headers=hs["oper_a"]).json()["total"] == 1
    assert mk_employee(client, hs["admin_b"], c["id"], code="E2").status_code == 404
    # Operators add and correct employees of their own vendor, but cannot deactivate them
    added = mk_employee(client, hs["oper_a"], c["id"], code="E3")
    assert added.status_code == 201
    eid = added.json()["id"]
    body = {k: added.json()[k] for k in ("employee_code", "first_name", "last_name", "mobile", "gender", "address", "latitude", "longitude", "site_id", "shift_id", "email")}
    assert client.put(f"/api/employees/{eid}", headers=hs["oper_a"], json={**body, "first_name": "Fixed"}).json()["first_name"] == "Fixed"
    assert client.patch(f"/api/employees/{eid}/status", headers=hs["oper_a"], json={"status": "inactive"}).status_code == 403
    assert client.put(f"/api/employees/{eid}", headers=hs["admin_b"], json=body).status_code == 404
    assert client.get("/api/employees", headers=hs["drv_a"]).status_code == 403


# ---------- drivers ----------
def test_driver_crud_and_validation(client, hs, lk):
    r = mk_driver(client, hs["admin_a"], lk, rest_days=["Sun"], languages=["English", "Hindi"], experience_months=24)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["code"] == f"DRV-{d['id']:05d}" and d["status"] == "active"
    assert mk_driver(client, hs["admin_a"], lk).status_code == 422  # same licence, same vendor
    assert mk_driver(client, hs["admin_a"], lk, lic="DL-2", contact_number="x").status_code == 422
    assert mk_driver(client, hs["admin_a"], lk, lic="DL-3", rest_days=["Funday"]).status_code == 422
    assert mk_driver(client, hs["admin_a"], lk, lic="DL-4", license_type_id=lk["vehicle_type"]["Sedan"]).status_code == 422
    assert mk_driver(client, hs["admin_a"], lk, lic="DL-5", gender=None).status_code == 422


def test_driver_licence_unique_per_vendor_only(client, hs, lk):
    assert mk_driver(client, hs["admin_a"], lk, lic="SAME").status_code == 201
    assert mk_driver(client, hs["admin_b"], lk, lic="SAME").status_code == 201


def test_driver_default_vehicle_must_be_same_vendor(client, hs, lk):
    vb = mk_vehicle(client, hs["admin_b"], lk, "KA01AA0001", "VB").json()
    r = mk_driver(client, hs["admin_a"], lk, default_vehicle_id=vb["id"])
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "default_vehicle_id"


def test_driver_visibility(client, hs, lk):
    d = mk_driver(client, hs["admin_a"], lk, emergency_contact="9000000000").json()
    assert client.get(f"/api/drivers/{d['id']}", headers=hs["admin_b"]).status_code == 404
    assert client.get("/api/drivers", headers=hs["admin_b"]).json()["total"] == 0
    # operators get a reduced view and no detail endpoint
    item = client.get("/api/drivers", headers=hs["oper_a"]).json()["items"][0]
    assert "license_number" not in item and "emergency_contact" not in item and item["first_name"] == "Dev"
    assert client.get(f"/api/drivers/{d['id']}", headers=hs["oper_a"]).status_code == 403
    assert client.get("/api/drivers", headers=hs["drv_a"]).status_code == 403


def test_driver_status_toggle(client, hs, lk):
    d = mk_driver(client, hs["admin_a"], lk).json()
    r = client.patch(f"/api/drivers/{d['id']}/status", headers=hs["admin_a"], json={"status": "inactive"})
    assert r.json()["status"] == "inactive"
    assert client.patch(f"/api/drivers/{d['id']}/status", headers=hs["admin_b"], json={"status": "active"}).status_code == 404


# ---------- vehicles ----------
def test_vehicle_rules(client, hs, lk):
    assert mk_vehicle(client, hs["admin_a"], lk, cap=0).status_code == 422
    assert mk_vehicle(client, hs["admin_a"], lk, cap=-2).status_code == 422
    v = mk_vehicle(client, hs["admin_a"], lk, "mh 12-ab 1234", "V1", 6)
    assert v.status_code == 201 and v.json()["vehicle_number"] == "MH12AB1234" and v.json()["code"].startswith("VEH-")
    # same plate in any other spelling is a duplicate – even for another vendor
    assert mk_vehicle(client, hs["admin_a"], lk, "MH12AB1234", "V2").status_code == 422
    assert mk_vehicle(client, hs["admin_b"], lk, "MH 12 AB 1234", "V9").status_code == 422
    # vehicle code unique per vendor only
    assert mk_vehicle(client, hs["admin_a"], lk, "MH12AB9999", "V1").status_code == 422
    assert mk_vehicle(client, hs["admin_b"], lk, "KA01AB0001", "V1").status_code == 201


def test_vehicle_visibility_and_permissions(client, hs, lk):
    v = mk_vehicle(client, hs["admin_a"], lk).json()
    assert client.get(f"/api/vehicles/{v['id']}", headers=hs["admin_b"]).status_code == 404
    assert client.get("/api/vehicles", headers=hs["admin_b"]).json()["total"] == 0
    assert client.get("/api/vehicles", headers=hs["oper_a"]).json()["total"] == 1
    body = {"vehicle_number": "MH12AB1234", "vehicle_code": "V1", "vehicle_type_id": v["vehicle_type_id"], "model": "x", "capacity": 4}
    assert client.put(f"/api/vehicles/{v['id']}", headers=hs["oper_a"], json=body).status_code == 403
    assert client.put(f"/api/vehicles/{v['id']}", headers=hs["admin_b"], json=body).status_code == 404
    # updating keeps its own number without a false duplicate error
    assert client.put(f"/api/vehicles/{v['id']}", headers=hs["admin_a"], json={**body, "capacity": 7}).json()["capacity"] == 7
    assert client.get("/api/vehicles", headers=hs["drv_a"]).status_code == 403


# ---------- driver login linking ----------
def test_driver_user_must_link_to_one_driver_record(client, hs, world, lk):
    d = mk_driver(client, hs["admin_a"], lk).json()
    other_vendor_driver = mk_driver(client, hs["admin_b"], lk, lic="B1").json()
    base = dict(first_name="Dan", last_name="Driver", username="dan", email="dan@example.com",
                role="driver", vendor_id=world["va"].id, address="1 Road")
    root = hs["root"]
    assert client.post("/api/users", headers=root, json=base).json()["detail"][0]["loc"][-1] == "driver_id"
    assert client.post("/api/users", headers=root, json={**base, "driver_id": other_vendor_driver["id"]}).status_code == 422
    ok = client.post("/api/users", headers=root, json={**base, "driver_id": d["id"]})
    assert ok.status_code == 201 and ok.json()["user"]["driver_id"] == d["id"]
    again = client.post("/api/users", headers=root, json={**base, "username": "dan2", "email": "d2@example.com", "driver_id": d["id"]})
    assert again.status_code == 422
    # only drivers get a link
    assert client.post("/api/users", headers=root, json={**base, "username": "op", "email": "op@example.com",
                                                         "role": "operator", "driver_id": d["id"]}).status_code == 422
    # linked drivers disappear from the "unlinked" picker
    assert client.get("/api/drivers?unlinked=true", headers=root).json()["total"] == 1  # only vendor B's driver left
