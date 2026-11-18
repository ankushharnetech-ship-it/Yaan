from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ApplicationSetting

# key -> default. Stored as strings ("true"/"false" or an integer).
DEFAULTS: dict[str, bool] = {
    # Which channels carry trip notifications to employees and drivers (confirmed: SMS on, Email off by default).
    # Both on = both are used; only one on = only that one; both off = nothing is sent (the trip itself is unaffected).
    # System emails (account onboarding, password reset) are not governed by these.
    "notify_sms_enabled": True,
    "notify_email_enabled": False,
    "sms_on_cancellation": True,    # confirmed: cancelling an assigned trip also notifies (over the enabled channels)
    "sms_on_reassignment": False,   # confirmed: configurable, default off
}
INT_DEFAULTS: dict[str, int] = {
    "compliance_expiry_warning_days": 30,  # spec 17: "about to expire" = within 30 days, configurable
}


def _raw(db: Session, key: str, vendor_id: int | None) -> str | None:
    """Vendor override wins, then the global default row; None if neither exists."""
    rows = {r.vendor_id: r.value for r in db.scalars(
        select(ApplicationSetting).where(ApplicationSetting.key == key,
                                         (ApplicationSetting.vendor_id == vendor_id) | ApplicationSetting.vendor_id.is_(None)))}
    if vendor_id is not None and vendor_id in rows:
        return rows[vendor_id]
    return rows.get(None)


def get_bool(db: Session, key: str, vendor_id: int | None) -> bool:
    v = _raw(db, key, vendor_id)
    return DEFAULTS[key] if v is None else v.strip().lower() == "true"


def get_int(db: Session, key: str, vendor_id: int | None) -> int:
    v = _raw(db, key, vendor_id)
    try:
        return INT_DEFAULTS[key] if v is None else int(v)
    except ValueError:
        return INT_DEFAULTS[key]


def channels(db: Session, vendor_id: int | None) -> tuple[bool, bool]:
    """(sms_enabled, email_enabled) for this vendor."""
    return get_bool(db, "notify_sms_enabled", vendor_id), get_bool(db, "notify_email_enabled", vendor_id)


def effective(db: Session, vendor_id: int | None) -> dict[str, bool | int]:
    return {**{k: get_bool(db, k, vendor_id) for k in DEFAULTS}, **{k: get_int(db, k, vendor_id) for k in INT_DEFAULTS}}


def _set(db: Session, key: str, value: str, vendor_id: int | None) -> None:
    q = select(ApplicationSetting).where(ApplicationSetting.key == key)
    q = q.where(ApplicationSetting.vendor_id == vendor_id) if vendor_id is not None else q.where(ApplicationSetting.vendor_id.is_(None))
    row = db.scalar(q)
    if row:
        row.value = value
    else:
        db.add(ApplicationSetting(key=key, value=value, vendor_id=vendor_id))


def set_bool(db: Session, key: str, value: bool, vendor_id: int | None) -> None:
    _set(db, key, "true" if value else "false", vendor_id)


def set_int(db: Session, key: str, value: int, vendor_id: int | None) -> None:
    _set(db, key, str(int(value)), vendor_id)
