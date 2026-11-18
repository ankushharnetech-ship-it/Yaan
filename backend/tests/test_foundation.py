from fastapi.testclient import TestClient

from app.core.permissions import has_permission
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_temp_password,
    hash_password,
    verify_password,
)
from app.main import app
from app.models import Role

client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "up"


def test_operator_cannot_manage_master_data():
    for perm in ("driver:write", "vehicle:write", "vendor:write", "settings:write", "user:write"):
        assert not has_permission(Role.OPERATOR, perm)
    for perm in ("trip:create", "trip:edit", "trip:cancel", "availability:read"):
        assert has_permission(Role.OPERATOR, perm)


def test_driver_limited_to_own_trip_flow():
    assert not has_permission(Role.DRIVER, "dashboard:view")
    assert not has_permission(Role.DRIVER, "trip:cancel")
    assert not has_permission(Role.DRIVER, "trip:create")
    assert has_permission(Role.DRIVER, "trip:driver_status")


def test_only_super_admin_manages_users_and_vendors():
    assert has_permission(Role.SUPER_ADMIN, "user:write")
    assert has_permission(Role.SUPER_ADMIN, "vendor:write")
    assert not has_permission(Role.VENDOR_ADMIN, "user:write")
    assert not has_permission(Role.VENDOR_ADMIN, "vendor:write")


def test_password_hashing_and_temp_password():
    pw = generate_temp_password()
    h = hash_password(pw)
    assert h != pw and verify_password(pw, h) and not verify_password("wrong", h)


def test_token_roundtrip_and_tamper():
    t = create_access_token(42)
    assert decode_access_token(t)["sub"] == "42"
    assert decode_access_token(t + "x") is None
