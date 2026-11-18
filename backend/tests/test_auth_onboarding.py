import re
from datetime import timedelta

from sqlalchemy import select

from app.models import AuditLog, EmailLog, Role, User
from app.services.auth_service import now
from tests.conftest import PASSWORD, auth, login, make_user

NEW_PW = "BrandNew#Pass9"


def create_user(client, headers, vendor_id, **over):
    body = dict(first_name="Olivia", last_name="Ops", username="olivia", email="olivia@example.com",
                role="operator", vendor_id=vendor_id, address="1 Road")
    body.update(over)
    if body["role"] == "operator" and vendor_id and "customer_id" not in body:
        root = auth(client, "root")
        found = client.get(f"/api/customers?vendor_id={vendor_id}", headers=root).json()["items"]
        body["customer_id"] = found[0]["id"] if found else client.post("/api/customers", headers=root, json={
            "code": "C1", "name": "Acme", "vendor_id": vendor_id, "address": "1 Road", "latitude": 18.5, "longitude": 73.8,
            "contact_person": "Desk", "email": "desk@example.com"}).json()["id"]
    return client.post("/api/users", json=body, headers=headers)


def link_token(outbox, idx=-1):
    return re.search(r"token=([\w-]+)", outbox.sent[idx]["text"]).group(1)


def test_login_wrong_password_is_generic(client, world):
    r1 = login(client, "root", "nope")
    r2 = login(client, "ghost", "nope")
    assert r1.status_code == r2.status_code == 401 and r1.json() == r2.json()


def test_login_rate_limited(client, world):
    for _ in range(8):
        login(client, "root", "bad")
    assert login(client, "root", "bad").status_code == 429


def test_super_admin_creates_user_full_flow(client, world, outbox, db):
    h = auth(client, "root")
    r = create_user(client, h, world["va"].id)
    assert r.status_code == 201, r.text
    data = r.json()
    temp = data["temporary_password"]
    assert temp and data["email_status"] == "sent"
    assert data["user"]["credential_status"] == "temporary"

    # expires in ~5 days
    exp = db.scalar(select(User.temp_password_expires_at).where(User.username == "olivia"))
    assert timedelta(days=4, hours=23) < exp - now() <= timedelta(days=5)

    # hash only; the plaintext appears nowhere in DB or email
    u = db.scalar(select(User).where(User.username == "olivia"))
    assert temp not in u.password_hash
    assert temp not in outbox.sent[0]["text"] and "olivia" in outbox.sent[0]["text"]
    assert "token=" in outbox.sent[0]["text"]
    assert db.scalar(select(EmailLog.status).where(EmailLog.template == "user_onboarding")) == "sent"

    # Temp login works but business endpoints are blocked until the password is changed
    oh = auth(client, "olivia", temp)
    assert client.get("/api/auth/me", headers=oh).json()["must_change_password"] is True
    blocked = client.get("/api/vendors", headers=oh)
    assert blocked.status_code == 403 and blocked.json()["detail"] == "password_change_required"

    ch = client.post("/api/auth/change-password", headers=oh,
                     json={"current_password": temp, "new_password": NEW_PW})
    assert ch.status_code == 200
    new_h = {"Authorization": f"Bearer {ch.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=new_h).json()["must_change_password"] is False
    assert client.get("/api/auth/me", headers=oh).status_code == 401  # old session revoked
    assert login(client, "olivia", temp).status_code == 401  # temp password invalidated
    assert login(client, "olivia", NEW_PW).status_code == 200

    actions = set(db.scalars(select(AuditLog.action)))
    assert {"user.created", "auth.login", "auth.password_changed"} <= actions


def test_set_password_link_from_email_works_once(client, world, outbox):
    h = auth(client, "root")
    create_user(client, h, world["va"].id)
    tok = link_token(outbox)
    assert client.post("/api/auth/reset-password", json={"token": tok, "new_password": NEW_PW}).status_code == 200
    assert login(client, "olivia", NEW_PW).status_code == 200
    again = client.post("/api/auth/reset-password", json={"token": tok, "new_password": "Another#Pass88"})
    assert again.status_code == 400


def test_expired_temp_password_blocks_login_but_forgot_flow_recovers(client, world, outbox, db):
    h = auth(client, "root")
    temp = create_user(client, h, world["va"].id).json()["temporary_password"]
    u = db.scalar(select(User).where(User.username == "olivia"))
    u.temp_password_expires_at = now() - timedelta(minutes=1)
    db.commit()

    r = login(client, "olivia", temp)
    assert r.status_code == 401 and "expired" in r.json()["detail"].lower()

    assert client.post("/api/auth/forgot-password", json={"identifier": "olivia@example.com"}).status_code == 200
    tok = link_token(outbox)
    assert client.post("/api/auth/reset-password", json={"token": tok, "new_password": NEW_PW}).status_code == 200
    assert login(client, "olivia", NEW_PW).status_code == 200


def test_forgot_password_does_not_reveal_accounts(client, world, outbox):
    a = client.post("/api/auth/forgot-password", json={"identifier": "ghost"})
    b = client.post("/api/auth/forgot-password", json={"identifier": "admin_a"})
    assert a.json() == b.json() and len(outbox.sent) == 1


def test_reset_token_expiry(client, world, outbox, db):
    client.post("/api/auth/forgot-password", json={"identifier": "admin_a"})
    tok = link_token(outbox)
    from app.models import PasswordResetToken
    t = db.scalar(select(PasswordResetToken))
    t.expires_at = now() - timedelta(seconds=1)
    db.commit()
    assert client.post("/api/auth/reset-password", json={"token": tok, "new_password": NEW_PW}).status_code == 400


def test_weak_password_rejected(client, world):
    h = auth(client, "admin_a")
    r = client.post("/api/auth/change-password", headers=h,
                    json={"current_password": PASSWORD, "new_password": "short1"})
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "new_password"


def test_duplicate_username_and_email_field_errors(client, world):
    h = auth(client, "root")
    assert create_user(client, h, world["va"].id).status_code == 201
    r = create_user(client, h, world["va"].id, email="other@example.com")
    assert r.status_code == 422 and r.json()["detail"][0]["loc"][-1] == "username"
    r = create_user(client, h, world["va"].id, username="olivia2")
    assert r.json()["detail"][0]["loc"][-1] == "email"


def test_vendor_required_and_no_super_admin_creation(client, world):
    h = auth(client, "root")
    assert create_user(client, h, None).json()["detail"][0]["loc"][-1] == "vendor_id"
    assert create_user(client, h, world["va"].id, role="super_admin").status_code == 422


def test_vendor_admin_onboards_operators_but_cannot_create_vendors(client, world):
    h = auth(client, "admin_a")
    r = create_user(client, h, world["va"].id)
    assert r.status_code == 201 and r.json()["user"]["role"] == "operator" and r.json()["temporary_password"]
    assert client.post("/api/vendors", headers=h, json={"name": "X", "code": "X"}).status_code == 403


def test_operator_and_driver_cannot_list_users(client, world, db):
    make_user(db, "oper", Role.OPERATOR, world["va"].id)
    make_user(db, "drv", Role.DRIVER, world["va"].id)
    for who in ("oper", "drv"):
        assert client.get("/api/users", headers=auth(client, who)).status_code == 403


def test_vendor_isolation_for_users(client, world, db):
    make_user(db, "oper_a", Role.OPERATOR, world["va"].id)
    ob = make_user(db, "oper_b", Role.OPERATOR, world["vb"].id)
    h = auth(client, "admin_a")
    names = {u["username"] for u in client.get("/api/users", headers=h).json()["items"]}
    assert names == {"admin_a", "oper_a"}
    assert client.get(f"/api/users/{ob.id}", headers=h).status_code == 404
    # vendor admin cannot see other vendors in the vendor list either
    assert [v["code"] for v in client.get("/api/vendors", headers=h).json()["items"]] == ["A"]


def test_inactive_user_cannot_login_and_session_dropped(client, world, db):
    make_user(db, "oper", Role.OPERATOR, world["va"].id)
    oh = auth(client, "oper")
    uid = db.scalar(select(User.id).where(User.username == "oper"))
    sa = auth(client, "root")
    assert client.patch(f"/api/users/{uid}/status", headers=sa, json={"status": "inactive"}).status_code == 200
    assert login(client, "oper").status_code == 401
    assert client.get("/api/auth/me", headers=oh).status_code == 401


def test_resend_onboarding_regenerates_and_rejects_completed(client, world, outbox):
    h = auth(client, "root")
    first = create_user(client, h, world["va"].id).json()
    uid = first["user"]["id"]
    second = client.post(f"/api/users/{uid}/resend-onboarding", headers=h).json()
    assert second["temporary_password"] != first["temporary_password"]
    assert login(client, "olivia", first["temporary_password"]).status_code == 401
    assert login(client, "olivia", second["temporary_password"]).status_code == 200
    # first set-password link was superseded
    old = re.search(r"token=([\w-]+)", outbox.sent[0]["text"]).group(1)
    assert client.post("/api/auth/reset-password", json={"token": old, "new_password": NEW_PW}).status_code == 400
    # once setup is done, resend is refused
    client.post("/api/auth/reset-password", json={"token": link_token(outbox), "new_password": NEW_PW})
    assert client.post(f"/api/users/{uid}/resend-onboarding", headers=h).status_code == 409


def test_email_failure_does_not_block_creation(client, world, monkeypatch):
    from app.services import email as m

    class Boom:
        def send(self, *a, **k):
            raise RuntimeError("provider down")

    monkeypatch.setattr(m, "get_provider", lambda: Boom())
    r = create_user(client, auth(client, "root"), world["va"].id)
    assert r.status_code == 201 and r.json()["email_status"] == "failed"


def test_edit_user_details(client, world):
    sa = auth(client, "root")
    uid = create_user(client, sa, world["va"].id).json()["user"]["id"]
    r = client.put(f"/api/users/{uid}", headers=sa, json={"first_name": "Olive", "mobile": "9876543210", "address": "2 Lane"})
    assert r.status_code == 200 and r.json()["first_name"] == "Olive" and r.json()["address"] == "2 Lane"
    # a Vendor Admin may edit their own vendor's operator too
    assert client.put(f"/api/users/{uid}", headers=auth(client, "admin_a"), json={"last_name": "Ops2"}).status_code == 200
    # username and role are not editable
    client.put(f"/api/users/{uid}", headers=sa, json={"username": "hacker", "role": "vendor_admin"})
    got = client.get(f"/api/users/{uid}", headers=sa).json()
    assert got["username"] == "olivia" and got["role"] == "operator"


def test_only_super_admin_can_delete_users(client, world, db):
    sa = auth(client, "root")
    uid = create_user(client, sa, world["va"].id).json()["user"]["id"]
    # Vendor Admin: forbidden, user remains
    assert client.delete(f"/api/users/{uid}", headers=auth(client, "admin_a")).status_code == 403
    assert db.get(User, uid) is not None
    # Super Admin: deleted (their reset token is cleaned up, the email record is kept)
    assert client.delete(f"/api/users/{uid}", headers=sa).status_code == 204
    db.expire_all()
    assert db.get(User, uid) is None
    assert client.get(f"/api/users/{uid}", headers=sa).status_code == 404
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "user.deleted")) is not None
    assert db.scalar(select(EmailLog.status).where(EmailLog.template == "user_onboarding")) == "sent"


def test_cannot_delete_self_or_super_admin_or_user_with_history(client, world, db):
    sa = auth(client, "root")
    root_id = db.scalar(select(User.id).where(User.username == "root"))
    assert client.delete(f"/api/users/{root_id}", headers=sa).status_code == 409
    uid = create_user(client, sa, world["va"].id).json()["user"]["id"]
    # the operator now appears as an actor in the append-only audit trail
    from app.services import audit
    audit.record(db, "trip.requested", db.get(User, uid))
    db.commit()
    r = client.delete(f"/api/users/{uid}", headers=sa)
    assert r.status_code == 409 and "Deactivate" in r.json()["detail"]
    assert client.get(f"/api/users/{uid}", headers=sa).status_code == 200
