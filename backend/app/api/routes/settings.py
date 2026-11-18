from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from app.api.common import field_error
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import User, Vendor
from app.services import app_settings, audit

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsIn(BaseModel):
    vendor_id: int | None = None  # Super Admin: a vendor, or omit to change the global default
    notify_sms_enabled: bool | None = None
    notify_email_enabled: bool | None = None
    sms_on_cancellation: bool | None = None
    sms_on_reassignment: bool | None = None
    compliance_expiry_warning_days: int | None = Field(default=None, ge=1, le=365)


def _target(scope: VendorScope, requested: int | None, db: Session) -> int | None:
    if not scope.is_global:
        return scope.vendor_id  # vendor admins can only ever touch their own vendor
    if requested is not None and db.get(Vendor, requested) is None:
        raise field_error("vendor_id", "Unknown vendor")
    return requested


@router.get("")
def read_settings(vendor_id: int | None = None, _: User = Depends(require_permission("settings:read")),
                  scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    vid = _target(scope, vendor_id, db)
    return {"vendor_id": vid, "values": app_settings.effective(db, vid)}


@router.put("")
def write_settings(body: SettingsIn, actor: User = Depends(require_permission("settings:write")),
                   scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    vid = _target(scope, body.vendor_id, db)
    changed = {}
    for key in app_settings.DEFAULTS:
        val = getattr(body, key)
        if val is not None:
            app_settings.set_bool(db, key, val, vid)
            changed[key] = val
    for key in app_settings.INT_DEFAULTS:
        val = getattr(body, key)
        if val is not None:
            app_settings.set_int(db, key, val, vid)
            changed[key] = val
    audit.record(db, "settings.updated", actor, entity_type="settings", vendor_id=vid, detail=changed)
    db.commit()
    return {"vendor_id": vid, "values": app_settings.effective(db, vid)}
