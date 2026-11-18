"""An Operator is a customer-company user: tagged to one customer, who they add employees and request trips for."""
from sqlalchemy import select

from app.models import Role, User
from tests.conftest import CONTACT, GEO, auth, employee_extras, make_user
from tests.test_request_workflow import create_user, request_trip
from tests.test_trips import BASE, create, driver_world, iso, lk, trip_body, w  # noqa: F401  (fixtures)


def second_customer(w, name="Globex"):
    c = w.post("/api/customers", {"code": "C2", "name": name, **GEO, **CONTACT})
    site = w.post("/api/sites", {"customer_id": c["id"], "name": "Plant", "address": "9 Other Rd"})
    emp = w.post("/api/employees", dict(customer_id=c["id"], employee_code="G1", first_name="Gina", last_name="G", mobile="9876543212",
                                        gender="female", **GEO, **employee_extras(w.client, w.h["admin_a"], c["id"], "G1")))
    return c, site, emp


# ---------------------------------------------------------------- creating operators
def test_an_operator_must_be_given_a_customer_of_their_vendor(w):
    none = create_user(w, "admin_a", customer_id=None)
    assert none.status_code == 422 and none.json()["detail"][0]["loc"][-1] == "customer_id"
    foreign = w.post("/api/customers", {"code": "FB", "name": "B Co", **GEO, **CONTACT}, h=w.h["admin_b"])
    assert create_user(w, "admin_a", customer_id=foreign["id"]).status_code == 422                   # another vendor's customer
    assert create_user(w, "admin_a", customer_id=999999).status_code == 422
    w.client.patch(f"/api/customers/{w.customer['id']}/status", headers=w.h["admin_a"], json={"status": "inactive"})
    assert create_user(w, "admin_a", customer_id=w.customer["id"]).status_code == 422                # must be active


def test_the_customer_is_stored_shown_and_returned_at_sign_in(w):
    r = create_user(w, "admin_a").json()
    assert r["user"]["customer_id"] == w.customer["id"] and r["user"]["customer_name"] == "Acme"
    listed = w.client.get("/api/users?role=operator", headers=w.h["admin_a"]).json()["items"]
    assert {u["username"]: u["customer_name"] for u in listed}["nia"] == "Acme"
    login = w.client.post("/api/auth/login", json={"username": "oper_a", "password": "Sup3rSecret!x"}).json()["user"]
    assert login["customer_id"] == w.customer["id"] and login["customer_name"] == "Acme"
    assert w.client.get("/api/auth/me", headers=w.h["oper_a"]).json()["customer_name"] == "Acme"
    assert w.client.get("/api/auth/me", headers=w.h["admin_a"]).json()["customer_id"] is None


def test_only_operators_carry_a_customer(w, db):
    assert create_user(w, "admin_a", role="driver", username="d1", email="d1@example.com", customer_id=w.customer["id"]).status_code == 422
    admin = make_user(db, "admin_a2", Role.VENDOR_ADMIN, w.world["va"].id)
    r = w.client.put(f"/api/users/{admin.id}", headers=w.h["root"], json={"customer_id": w.customer["id"]})
    assert r.status_code == 422


def test_an_admin_can_move_an_operator_to_another_customer(w, db):
    other, _, _ = second_customer(w)
    me = db.scalar(select(User).where(User.username == "oper_a"))
    r = w.client.put(f"/api/users/{me.id}", headers=w.h["admin_a"], json={"customer_id": other["id"]})
    assert r.status_code == 200 and r.json()["customer_name"] == "Globex"
    assert w.client.put(f"/api/users/{me.id}", headers=w.h["admin_a"], json={"customer_id": None}).status_code == 422   # cannot be untagged
    assert w.client.put(f"/api/users/{me.id}", headers=w.h["oper_a"], json={"customer_id": w.customer["id"]}).status_code == 403


# ---------------------------------------------------------------- what an operator sees and creates
def test_employees_are_added_for_the_operators_own_customer_whatever_is_sent(w):
    other, _, _ = second_customer(w)
    ex = employee_extras(w.client, w.h["admin_a"], w.customer["id"], "NEW1")
    r = w.client.post("/api/employees", headers=w.h["oper_a"], json=dict(
        customer_id=other["id"], employee_code="NEW1", first_name="Nia", last_name="O", mobile="9876543299", gender="female", **GEO, **ex))
    assert r.status_code == 201 and r.json()["customer_id"] == w.customer["id"]                      # forced to Acme, not Globex
    omitted = w.client.post("/api/employees", headers=w.h["oper_a"], json=dict(
        employee_code="NEW2", first_name="Omi", last_name="O", mobile="9876543298", gender="male", **GEO,
        **employee_extras(w.client, w.h["admin_a"], w.customer["id"], "NEW2")))
    assert omitted.status_code == 201 and omitted.json()["customer_id"] == w.customer["id"]            # no customer needed in the form


def test_an_operator_sees_only_their_customers_employees_trips_and_customer(w):
    other, osite, oemp = second_customer(w)
    mine = request_trip(w).json()
    theirs = w.client.post("/api/trips", headers=w.h["admin_a"], json=dict(
        customer_id=other["id"], site_id=osite["id"], trip_type_id=w.pickup, scheduled_start=iso(300), scheduled_end=iso(360),
        pickup_address="A", drop_address="B", employee_ids=[oemp["id"]])).json()
    op = w.h["oper_a"]
    assert {e["customer_id"] for e in w.client.get("/api/employees?limit=200", headers=op).json()["items"]} == {w.customer["id"]}
    assert w.client.get(f"/api/employees/{oemp['id']}", headers=op).status_code == 404
    full = {k: oemp[k] for k in ("employee_code", "first_name", "last_name", "mobile", "gender", "address", "latitude", "longitude", "site_id", "shift_id", "email")}
    assert w.client.put(f"/api/employees/{oemp['id']}", headers=op, json=full).status_code == 404
    ids = {t["id"] for t in w.client.get("/api/trips?view=all", headers=op).json()["items"]}
    assert ids == {mine["id"]}
    assert w.client.get(f"/api/trips/{theirs['id']}", headers=op).status_code == 404
    assert [c["id"] for c in w.client.get("/api/customers", headers=op).json()["items"]] == [w.customer["id"]]
    admin_ids = {t["id"] for t in w.client.get("/api/trips?view=all", headers=w.h["admin_a"]).json()["items"]}
    assert admin_ids == {mine["id"], theirs["id"]}                                                    # admins still see everything


def test_a_trip_request_is_always_for_the_operators_customer(w):
    other, osite, oemp = second_customer(w)
    body = trip_body(w)
    body.pop("driver_id"), body.pop("vehicle_id")
    omitted = {k: v for k, v in body.items() if k != "customer_id"}
    r = w.client.post("/api/trips", headers=w.h["oper_a"], json=omitted)
    assert r.status_code == 201 and r.json()["customer_id"] == w.customer["id"]                       # no customer field needed
    sneaky = w.client.post("/api/trips", headers=w.h["oper_a"], json={**body, "customer_id": other["id"], "employee_ids": [oemp["id"]]})
    assert sneaky.status_code == 422                                                                  # Globex's people are not Acme's to send


def test_an_untagged_operator_is_told_to_ask_their_admin(w, db):
    make_user(db, "oper_new", Role.OPERATOR, w.world["va"].id)
    h = auth(w.client, "oper_new")
    full = dict(customer_id=w.customer["id"], employee_code="U1", first_name="U", last_name="N", mobile="9876543277", gender="male", **GEO,
                **employee_extras(w.client, w.h["admin_a"], w.customer["id"], "U1"))
    r = w.client.post("/api/employees", headers=h, json=full)
    assert r.status_code == 409 and "not linked to a customer" in r.json()["detail"]
    body = trip_body(w)
    body.pop("driver_id"), body.pop("vehicle_id")
    t = w.client.post("/api/trips", headers=h, json=body)
    assert t.status_code == 409 and "assign" in t.json()["detail"]
    assert w.client.get("/api/auth/me", headers=h).json()["customer_id"] is None
