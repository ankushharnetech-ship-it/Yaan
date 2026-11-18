from datetime import timedelta
from io import BytesIO

import pytest
from openpyxl import load_workbook
from sqlalchemy import select, update

from app.models import AuditLog, Expense, LookupValue
from app.services.compliance import today
from tests.conftest import auth
from tests.test_trips import driver_world, lk, w  # noqa: F401  (fixtures)


@pytest.fixture
def cat(db):
    return {r.label: r.id for r in db.scalars(select(LookupValue).where(LookupValue.category == "expense_category"))}


def day(n: int = 0) -> str:
    return (today() + timedelta(days=n)).isoformat()


def add(w, cat, who="admin_a", category="Fuel", amount="1000.50", **kw):
    h = w.h[who] if isinstance(who, str) else who
    body = dict(expense_date=day(), category_id=cat[category], amount=amount, payment_method="cash")
    body.update(kw)
    return w.client.post("/api/expenses", headers=h, json=body)


def lst(w, who, qs=""):
    h = w.h[who] if isinstance(who, str) else who
    return w.client.get(f"/api/expenses{'?' + qs if qs else ''}", headers=h)


@pytest.fixture
def team(driver_world, cat):
    """One expense each from a driver, an operator and the vendor admin (vendor A), one from vendor B's admin."""
    w = driver_world
    w.e_drv = add(w, cat, w.dh1, "Fuel", "1500.00", payment_method="fuel_card", vehicle_id=w.v4["id"], description="Diesel fill").json()
    w.e_op = add(w, cat, "oper_a", "Toll & parking", "250.00", payment_method="upi").json()
    w.e_adm = add(w, cat, "admin_a", "Maintenance & repair", "8000.00", payment_method="bank_transfer",
                  vehicle_id=w.v6["id"], driver_id=w.d2["id"]).json()
    w.e_b = add(w, cat, "admin_b", "Insurance", "20000.00", payment_method="card").json()
    return w


# ---------------------------------------------------------------- everyone can add; who did it is stored
def test_every_role_can_record_an_expense_and_the_entrant_is_stored(driver_world, cat):
    w = driver_world
    for who, role in (("admin_a", "vendor_admin"), ("oper_a", "operator"), (w.dh1, "driver")):
        r = add(w, cat, who)
        assert r.status_code == 201, (who, r.text)
        e = r.json()
        assert e["code"] == f"EXP-{e['id']:06d}" and e["entered_by"] and e["entered_by_role"] == role
        assert e["amount"] == 1000.5 and e["status"] == "recorded" and e["vendor_id"] == w.world["va"].id
        assert e["category"] == "Fuel" and e["payment_method_label"] == "Cash"


def test_vendor_is_pinned_and_super_admin_must_choose(driver_world, cat):
    w = driver_world
    spoof = add(w, cat, "admin_a", vendor_id=w.world["vb"].id)                  # tries to book into another vendor
    assert spoof.json()["vendor_id"] == w.world["va"].id
    no_vendor = add(w, cat, "root")
    assert no_vendor.status_code == 422 and no_vendor.json()["detail"][0]["loc"][-1] == "vendor_id"
    ok = add(w, cat, "root", vendor_id=w.world["vb"].id)
    assert ok.status_code == 201 and ok.json()["vendor_id"] == w.world["vb"].id and ok.json()["entered_by_role"] == "super_admin"


def test_validation(driver_world, cat):
    w = driver_world
    for bad in ({"amount": "0"}, {"amount": "-5"}, {"amount": "10.999"}, {"amount": "99999999"}, {"amount": "abc"},
                {"expense_date": day(1)}, {"category_id": 999999}, {"payment_method": "bitcoin"}):
        assert add(w, cat, **bad).status_code == 422, bad
    assert add(w, cat, category="Fuel", expense_date=day(-400)).status_code == 201            # back-dating is allowed
    wrong_cat = add(w, cat, category_id=w.lk["vehicle_type"]["Sedan"])
    assert wrong_cat.status_code == 422 and wrong_cat.json()["detail"][0]["loc"][-1] == "category_id"


def test_vehicle_and_driver_must_belong_to_the_vendor(driver_world, cat):
    w = driver_world
    other_v = w.post("/api/vehicles", dict(vehicle_number="KA01ZZ0001", vehicle_code="KZ1", vehicle_type_id=w.lk["vehicle_type"]["Sedan"],
                                           model="M", capacity=4), h=w.h["admin_b"])
    other_d = w.post("/api/drivers", dict(first_name="B", last_name="D", contact_number="9000000077", gender="male",
                                          license_type_id=w.lk["license_type"]["LMV"], license_number="BZ1", email="d@example.com", date_of_joining="2024-01-01", experience_months=12, emergency_contact="9000000000", home_address="1 Road"), h=w.h["admin_b"])
    assert add(w, cat, vehicle_id=other_v["id"]).json()["detail"][0]["loc"][-1] == "vehicle_id"
    assert add(w, cat, driver_id=other_d["id"]).json()["detail"][0]["loc"][-1] == "driver_id"
    ok = add(w, cat, vehicle_id=w.v4["id"], driver_id=w.d2["id"]).json()
    assert ok["vehicle_number"] == "MH01AA0004" and ok["driver_name"] == "L2 D"


def test_a_driver_can_only_attribute_expenses_to_themselves(driver_world, cat):
    w = driver_world
    e = add(w, cat, w.dh1, driver_id=w.d2["id"]).json()                         # tries to blame driver 2
    assert e["driver_id"] == w.d1["id"] and e["driver_name"] == "L1 D"
    assert add(w, cat, "oper_a", driver_id=w.d2["id"]).json()["driver_id"] == w.d2["id"]   # operators may choose


# ---------------------------------------------------------------- who sees what
def test_visibility_follows_role(team):
    w = team
    ids = lambda who, qs="": {e["id"] for e in lst(w, who, qs).json()["items"]}  # noqa: E731
    assert ids(w.dh1) == {w.e_drv["id"]}                                          # driver: only their own
    assert ids("oper_a") == {w.e_op["id"]}                                        # operator: only their own
    assert ids("admin_a") == {w.e_drv["id"], w.e_op["id"], w.e_adm["id"]}         # vendor admin: whole vendor
    assert ids("admin_b") == {w.e_b["id"]}                                        # other vendor sees only its own
    assert ids("root") == {w.e_drv["id"], w.e_op["id"], w.e_adm["id"], w.e_b["id"]}
    assert ids("root", f"vendor_id={w.world['vb'].id}") == {w.e_b["id"]}
    # filters can't be used to peek at colleagues' entries
    assert ids("oper_a", f"entered_by={w.e_drv['entered_by_id']}") == {w.e_op["id"]}
    assert ids("admin_a", f"entered_by={w.e_op['entered_by_id']}") == {w.e_op["id"]}


def test_detail_access(team):
    w = team
    get = lambda who, e: w.client.get(f"/api/expenses/{e['id']}", headers=w.h[who] if isinstance(who, str) else who)  # noqa: E731
    assert get(w.dh1, w.e_drv).status_code == 200
    assert get(w.dh1, w.e_op).status_code == 404 and get("oper_a", w.e_drv).status_code == 404
    assert get("admin_a", w.e_drv).status_code == 200
    assert get("admin_b", w.e_drv).status_code == 404 and get("admin_a", w.e_b).status_code == 404


def test_list_filters_and_total_amount(team, cat):
    w = team
    r = lst(w, "admin_a").json()
    assert r["total"] == 3 and r["total_amount"] == 9750.0
    assert lst(w, "admin_a", f"category_id={cat['Fuel']}").json()["total_amount"] == 1500.0
    assert lst(w, "admin_a", f"vehicle_id={w.v6['id']}").json()["total"] == 1
    assert lst(w, "admin_a", "payment_method=upi").json()["total"] == 1
    assert lst(w, "admin_a", "q=diesel").json()["total"] == 1
    assert lst(w, "admin_a", f"date_from={day(1)}").json()["total"] == 0
    assert lst(w, "admin_a", "limit=1").json()["total"] == 3 and len(lst(w, "admin_a", "limit=1").json()["items"]) == 1


# ---------------------------------------------------------------- edit window / void
def test_creator_can_edit_only_inside_the_window(team, cat, db):
    w = team
    put = lambda who, e, **kw: w.client.put(f"/api/expenses/{e['id']}", headers=w.h[who] if isinstance(who, str) else who, json={  # noqa: E731
        "expense_date": day(), "category_id": cat["Fuel"], "amount": "1750.00", "payment_method": "cash", **kw})
    r = put(w.dh1, w.e_drv)
    assert r.status_code == 200 and r.json()["amount"] == 1750.0 and r.json()["can_edit"] is True
    assert put(w.dh1, w.e_op).status_code == 404                                  # someone else's
    db.execute(update(Expense).values(created_at=Expense.created_at - timedelta(hours=25)))
    db.commit()
    late = put(w.dh1, w.e_drv)
    assert late.status_code == 403 and "edit window" in late.json()["detail"]
    assert lst(w, w.dh1).json()["items"][0]["can_edit"] is False
    assert put("admin_a", w.e_drv, amount="1800.00").status_code == 200           # admins: any time
    assert put("admin_b", w.e_drv).status_code == 404                              # but only in their own vendor
    assert put("oper_a", w.e_op).status_code == 403                                # operator also locked after 24 h


def test_void_keeps_history_and_leaves_the_totals(team, db):
    w = team
    assert w.client.post(f"/api/expenses/{w.e_op['id']}/void", headers=w.h["oper_a"], json={"reason": ""}).status_code == 422
    v = w.client.post(f"/api/expenses/{w.e_op['id']}/void", headers=w.h["oper_a"], json={"reason": "Entered twice"})
    assert v.status_code == 200 and v.json()["status"] == "voided" and v.json()["void_reason"] == "Entered twice"
    assert v.json()["voided_by"] and v.json()["voided_at"] and v.json()["can_edit"] is False
    assert w.client.post(f"/api/expenses/{w.e_op['id']}/void", headers=w.h["oper_a"], json={"reason": "again"}).status_code == 409
    again = w.client.put(f"/api/expenses/{w.e_op['id']}", headers=w.h["admin_a"], json={
        "expense_date": day(), "category_id": w.e_op["category_id"], "amount": "1", "payment_method": "cash"})
    assert again.status_code == 409                                                # voided entries are frozen
    r = lst(w, "admin_a").json()
    assert r["total"] == 3 and r["total_amount"] == 9500.0                         # still listed, not counted
    assert lst(w, "admin_a", "status=voided").json()["total"] == 1
    assert db.get(Expense, w.e_op["id"]) is not None                               # never hard-deleted
    assert w.client.post(f"/api/expenses/{w.e_drv['id']}/void", headers=w.h["oper_a"], json={"reason": "not mine"}).status_code == 404
    assert w.client.post(f"/api/expenses/{w.e_b['id']}/void", headers=w.h["admin_a"], json={"reason": "other vendor"}).status_code == 404


def test_expense_actions_are_audited(team, db):
    w = team
    w.client.post(f"/api/expenses/{w.e_op['id']}/void", headers=w.h["oper_a"], json={"reason": "Entered twice"})
    w.client.put(f"/api/expenses/{w.e_drv['id']}", headers=w.dh1, json={
        "expense_date": day(), "category_id": w.e_drv["category_id"], "amount": "1600", "payment_method": "cash"})
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"expense.created", "expense.updated", "expense.voided"} <= actions


# ---------------------------------------------------------------- summaries (Super Admin all vendors, Vendor Admin own vendor)
def summary(w, who, qs="range=this_month"):
    h = w.h[who] if isinstance(who, str) else who
    return w.client.get(f"/api/expenses/summary?{qs}", headers=h)


def test_only_admins_get_summaries(team):
    w = team
    for who in ("oper_a", w.dh1):
        assert summary(w, who).status_code == 403
    assert summary(w, "admin_a").status_code == 200 and summary(w, "root").status_code == 200


def test_vendor_admin_summary_is_vendor_level(team, cat):
    w = team
    s = summary(w, "admin_a").json()
    assert s["total"] == 9750.0 and s["count"] == 3 and s["average"] == 3250.0 and s["by_vendor"] == []
    assert {c["name"]: c["amount"] for c in s["by_category"]} == {"Maintenance & repair": 8000.0, "Fuel": 1500.0, "Toll & parking": 250.0}
    assert {p["name"]: p["amount"] for p in s["by_payment"]} == {"Bank transfer": 8000.0, "Company fuel card": 1500.0, "UPI": 250.0}
    assert {v["name"]: v["amount"] for v in s["by_vehicle"]} == {"MH01AA0006": 8000.0, "MH01AA0004": 1500.0}
    assert s["without_vehicle"] == 250.0
    who = {p["role"]: p["amount"] for p in s["by_person"]}
    assert who == {"vendor_admin": 8000.0, "driver": 1500.0, "operator": 250.0}
    assert s["trend"][-1]["amount"] == 9750.0 or sum(t["amount"] for t in s["trend"]) == 9750.0
    # vendor B's figures never leak into vendor A's summary, and a vendor_id parameter cannot widen it
    assert summary(w, "admin_a", f"range=this_month&vendor_id={w.world['vb'].id}").json()["total"] == 9750.0
    assert summary(w, "admin_b").json()["total"] == 20000.0


def test_super_admin_sees_every_vendor(team):
    w = team
    s = summary(w, "root").json()
    assert s["total"] == 29750.0 and s["count"] == 4
    assert {v["name"]: v["amount"] for v in s["by_vendor"]} == {"Alpha": 9750.0, "Bravo": 20000.0}
    only_b = summary(w, "root", f"range=this_month&vendor_id={w.world['vb'].id}").json()
    assert only_b["total"] == 20000.0 and only_b["vendor_id"] == w.world["vb"].id


def test_summary_ignores_voided_and_compares_with_previous_period(team, cat):
    w = team
    first_of_month = today().replace(day=1)
    add(w, cat, "admin_a", "Fuel", "3250.00", expense_date=(first_of_month - timedelta(days=1)).isoformat())   # last month
    w.client.post(f"/api/expenses/{w.e_op['id']}/void", headers=w.h["oper_a"], json={"reason": "dup"})
    s = summary(w, "admin_a").json()
    assert s["total"] == 9500.0 and s["count"] == 2 and s["voided_count"] == 1
    assert s["previous_total"] == 3250.0 and s["change_pct"] == pytest.approx(192.3, abs=0.1)
    last = summary(w, "admin_a", "range=last_month").json()
    assert last["total"] == 3250.0 and last["count"] == 1


def test_summary_ranges_and_validation(team, cat):
    w = team
    add(w, cat, "admin_a", "Fuel", "100.00", expense_date=day(-100))
    custom = summary(w, "admin_a", f"range=custom&date_from={day(-120)}&date_to={day(-80)}").json()
    assert custom["total"] == 100.0 and custom["trend_unit"] == "day"
    year = summary(w, "admin_a", "range=this_year").json()
    assert year["trend_unit"] == "month"
    for qs in ("range=custom", "range=custom&date_from=2030-02-01&date_to=2030-01-01", "range=forever",
               "range=custom&date_from=2000-01-01&date_to=2030-01-01"):
        assert summary(w, "admin_a", qs).status_code == 422, qs


# ---------------------------------------------------------------- pick-lists, reports
def test_form_options_are_scoped(driver_world):
    w = driver_world
    drv = w.client.get("/api/expenses/options", headers=w.dh1).json()
    assert [d["id"] for d in drv["drivers"]] == [w.d1["id"]] and drv["own_driver_id"] == w.d1["id"]    # only themselves
    assert len(drv["vehicles"]) == 3 and "Fuel" in [c["label"] for c in drv["categories"]]
    assert len(w.client.get("/api/expenses/options", headers=w.h["oper_a"]).json()["drivers"]) == 2
    assert w.client.get("/api/expenses/options", headers=w.h["admin_b"]).json()["vehicles"] == []
    assert w.client.get("/api/expenses/options", headers=w.h["root"]).json()["vehicles"] == []           # SA must choose a vendor first
    assert len(w.client.get(f"/api/expenses/options?vendor_id={w.world['va'].id}", headers=w.h["root"]).json()["vehicles"]) == 3


def test_expense_report_is_admin_only_and_exports(team):
    w = team
    rep = w.client.get("/api/reports/expenses?range=this_month", headers=w.h["admin_a"]).json()
    assert rep["summary"]["Total (INR)"] == 9750.0 and len(rep["rows"]) == 3
    assert {r["by"] for r in rep["rows"]} and {"Driver", "Operator", "Vendor Admin"} == {r["role"] for r in rep["rows"]}
    assert w.client.get("/api/reports/expenses", headers=w.h["oper_a"]).status_code == 403
    assert w.client.get("/api/reports/expenses", headers=w.dh1).status_code == 403
    assert "expenses" not in {r["key"] for r in w.client.get("/api/reports", headers=w.h["oper_a"]).json()["items"]}
    assert "expenses" in {r["key"] for r in w.client.get("/api/reports", headers=w.h["admin_a"]).json()["items"]}
    assert w.client.get("/api/reports/expenses", headers=w.h["admin_b"]).json()["summary"]["Total (INR)"] == 20000.0
    assert w.client.get("/api/reports/expenses", headers=w.h["root"]).json()["summary"]["Total (INR)"] == 29750.0
    x = w.client.get("/api/reports/expenses?format=xlsx", headers=w.h["admin_a"])
    assert x.status_code == 200
    flat = [c.value for row in load_workbook(BytesIO(x.content)).active.iter_rows() for c in row]
    assert "Expense ID" in flat and "Entered by" in flat and 8000.0 in flat


def test_requires_login(client):
    assert client.get("/api/expenses").status_code == 401
    assert client.get("/api/expenses/summary").status_code == 401
