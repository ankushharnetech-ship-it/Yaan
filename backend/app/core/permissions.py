"""Single source of truth for role -> permission mapping (spec section 3).

Permissions are `resource:action` strings. Endpoints declare the permission they
need via `require_permission`; vendor scoping is applied separately by `VendorScope`.
"""
from app.models.enums import Role

P = {
    "dashboard:view",
    "vendor:read", "vendor:write",
    "user:read", "user:write",   # user:write = create/manage anyone (Super Admin)
    "user:manage",               # create/manage Operators and Drivers of one's own vendor (Vendor Admin)
    "customer:read", "customer:write",
    "employee:read", "employee:create", "employee:write",  # create = add/edit; write = also activate/deactivate
    "driver:read", "driver:write",
    "vehicle:read", "vehicle:write",
    "availability:read",
    "trip:read", "trip:create", "trip:edit", "trip:cancel", "trip:assign",
    "trip:driver_status",  # Accepted / Started / Completed (own trips only)
    "compliance:read", "compliance:write",
    "report:read",
    "notification:read",
    "settings:read", "settings:write",
    "audit:read",
    "expense:create",   # everyone: add expenses and see/edit their own
    "expense:manage",   # see, edit and void every expense in scope
    "expense:summary",  # expense totals and breakdowns
}

_ALL = set(P)

ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.SUPER_ADMIN: _ALL - {"trip:driver_status"},
    Role.VENDOR_ADMIN: {
        "dashboard:view", "vendor:read", "user:read", "user:manage",
        "customer:read", "customer:write", "employee:read", "employee:create", "employee:write",
        "driver:read", "driver:write", "vehicle:read", "vehicle:write",
        "availability:read",
        "trip:read", "trip:create", "trip:edit", "trip:cancel", "trip:assign",
        "compliance:read", "compliance:write", "report:read", "notification:read",
        "settings:read", "settings:write", "audit:read",
        "expense:create", "expense:manage", "expense:summary",
    },
    Role.OPERATOR: {
        "dashboard:view", "customer:read", "employee:read", "employee:create",
        "driver:read", "vehicle:read", "availability:read",
        # Operators REQUEST trips (employees only) and manage requests still awaiting assignment.
        # Assigning a driver + vehicle ("trip:assign") belongs to the Vendor Admin.
        "trip:read", "trip:create", "trip:edit", "trip:cancel",
        "compliance:read", "report:read", "notification:read", "audit:read", "expense:create",
    },
    Role.DRIVER: {"trip:read", "trip:driver_status", "notification:read", "compliance:read", "audit:read",
                   "expense:create"},
}


def has_permission(role: Role, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
