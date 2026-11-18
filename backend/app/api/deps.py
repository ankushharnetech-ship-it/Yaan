"""Authentication + authorization dependencies. Every protected route uses these."""
from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.permissions import has_permission
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import ActiveStatus, Role, User, Vendor

bearer = HTTPBearer(auto_error=False)


def get_user_allow_pending(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    """Authenticated user, even if they still must replace their temporary password."""
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    if creds is None:
        raise unauthorized
    payload = decode_access_token(creds.credentials)
    if not payload:
        raise unauthorized
    user = db.get(User, int(payload["sub"]))
    if user is None or user.status != ActiveStatus.ACTIVE or payload.get("tv") != user.token_version:
        raise unauthorized
    if user.vendor_id is not None:  # a deactivated vendor locks out all of its users immediately
        vendor = db.get(Vendor, user.vendor_id)
        if vendor is None or vendor.status != ActiveStatus.ACTIVE:
            raise unauthorized
    return user


def get_current_user(user: User = Depends(get_user_allow_pending)) -> User:
    """Used by every business endpoint: blocks users who haven't set their own password yet."""
    if user.initial_setup_completed_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "password_change_required")
    return user


def require_permission(permission: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to do this")
        return user

    return checker


def require_any_permission(*permissions: str):
    """Pass if the caller holds at least one of the permissions (e.g. user:write OR user:manage)."""
    def checker(user: User = Depends(get_current_user)) -> User:
        if not any(has_permission(user.role, p) for p in permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not have permission to do this")
        return user

    return checker


@dataclass(frozen=True)
class VendorScope:
    """Which vendor(s) the caller may touch. `vendor_id=None` means all (Super Admin)."""

    vendor_id: int | None

    @property
    def is_global(self) -> bool:
        return self.vendor_id is None

    def ensure(self, record_vendor_id: int | None) -> None:
        """Raise 404 (not 403, to avoid leaking existence) if record is outside scope."""
        if not self.is_global and record_vendor_id != self.vendor_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def get_vendor_scope(user: User = Depends(get_current_user)) -> VendorScope:
    return VendorScope(None if user.role == Role.SUPER_ADMIN else user.vendor_id)
