from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import VendorScope, get_vendor_scope, require_any_permission, require_permission
from app.core.permissions import has_permission
from app.core.config import get_settings
from app.core.security import generate_temp_password, hash_password
from app.db.session import get_db
from app.models import ActiveStatus, Customer, Driver, EmailLog, PasswordResetToken, Role, User, Vendor
from app.schemas import OnboardingResult, StatusIn, UserCreate, UserOut, UserUpdate
from app.services import audit, auth_service as svc, email as mail

router = APIRouter(prefix="/users", tags=["users"])


def _customer_name(db: Session, customer_id: int | None) -> str | None:
    c = db.get(Customer, customer_id) if customer_id else None
    return c.name if c else None


def _check_customer(db: Session, vendor_id: int, customer_id: int | None) -> None:
    """An Operator belongs to one active customer of their own vendor."""
    c = db.get(Customer, customer_id) if customer_id else None
    if c is None or c.vendor_id != vendor_id or c.status != ActiveStatus.ACTIVE:
        raise _field_error("customer_id", "Select an active customer of this vendor")


def _out(u: User, vendor_name: str | None, customer_name: str | None = None) -> UserOut:
    if u.initial_setup_completed_at is not None:
        cred = "set"
    else:
        cred = "temporary_expired" if svc.temp_password_expired(u) else "temporary"
    out = UserOut.model_validate(u)
    out.vendor_name = vendor_name
    out.customer_name = customer_name
    out.credential_status = cred
    return out


def _vendor_name(db: Session, vendor_id: int | None) -> str | None:
    v = db.get(Vendor, vendor_id) if vendor_id else None
    return v.name if v else None


def _field_error(field: str, msg: str):
    return HTTPException(422, detail=[{"loc": ["body", field], "msg": msg}])


def _is_limited(actor: User) -> bool:
    """A Vendor Admin (user:manage but not user:write) may only manage Operators and Drivers of their own vendor."""
    return not has_permission(actor.role, "user:write")


def _ensure_manageable(actor: User, target: User) -> None:
    if _is_limited(actor) and target.role not in (Role.OPERATOR, Role.DRIVER):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only manage Operators and Drivers")


def _get_scoped(db: Session, scope: VendorScope, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    scope.ensure(u.vendor_id)
    return u


def _issue_credentials(db: Session, u: User) -> tuple[str, str]:
    """New temp password (hash only stored) + one-time set-password link; both valid for N days."""
    s = get_settings()
    temp = generate_temp_password()
    u.password_hash = hash_password(temp)
    u.initial_setup_completed_at = None
    u.temp_password_expires_at = svc.now() + timedelta(days=s.temp_password_days)
    u.token_version += 1
    raw = svc.create_reset_token(db, u, minutes=s.temp_password_days * 24 * 60)
    return temp, f"{s.frontend_url}/reset-password?token={raw}"


def _send_onboarding(db: Session, u: User, link: str) -> str:
    subject, text, html = mail.onboarding_email(u.first_name, u.username, u.temp_password_expires_at, link,
                                                last_name=u.last_name, role=u.role.value)
    entry = mail.send_and_log(db, to=u.email, subject=subject, text=text, html=html, to_name=f"{u.first_name} {u.last_name}".strip(),
                              template="user_onboarding", user_id=u.id, vendor_id=u.vendor_id)
    return entry.status


@router.post("", response_model=OnboardingResult, status_code=201)
def create_user(
    body: UserCreate, actor: User = Depends(require_any_permission("user:write", "user:manage")), db: Session = Depends(get_db)
):
    if body.role == Role.SUPER_ADMIN:
        raise _field_error("role", "Super Admin accounts cannot be created here")
    if _is_limited(actor):
        if body.role not in (Role.OPERATOR, Role.DRIVER):
            raise _field_error("role", "You can create Operators and Drivers")
        body = body.model_copy(update={"vendor_id": actor.vendor_id})  # always their own vendor, whatever was sent
    if body.vendor_id is None:
        raise _field_error("vendor_id", "Vendor is required for this role")
    vendor = db.get(Vendor, body.vendor_id)
    if vendor is None or vendor.status != ActiveStatus.ACTIVE:
        raise _field_error("vendor_id", "Select an active vendor")
    if body.role == Role.DRIVER:
        drv = db.get(Driver, body.driver_id) if body.driver_id else None
        if drv is None or drv.vendor_id != body.vendor_id:
            raise _field_error("driver_id", "Select a driver record of this vendor")
        if db.scalar(select(User.id).where(User.driver_id == drv.id)):
            raise _field_error("driver_id", "This driver already has a login")
    elif body.driver_id is not None:
        raise _field_error("driver_id", "Only Driver users are linked to a driver record")
    if body.role == Role.OPERATOR:
        _check_customer(db, body.vendor_id, body.customer_id)
    elif body.customer_id is not None:
        raise _field_error("customer_id", "Only Operators are tagged to a customer")
    if db.scalar(select(User.id).where(func.lower(User.username) == body.username.lower())):
        raise _field_error("username", "Username is already taken")
    if db.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise _field_error("email", "Email is already in use")

    u = User(**body.model_dump(exclude={"email"}), email=str(body.email).lower(), password_hash="x")
    db.add(u)
    db.flush()
    temp, link = _issue_credentials(db, u)
    audit.record(db, "user.created", actor, entity_type="user", entity_id=u.id, vendor_id=u.vendor_id,
                 detail={"role": u.role.value, "username": u.username})
    email_status = _send_onboarding(db, u, link)
    db.commit()
    return OnboardingResult(user=_out(u, vendor.name, _customer_name(db, u.customer_id)), temporary_password=temp,
                            temp_password_expires_at=u.temp_password_expires_at, email_status=email_status)


@router.get("")
def list_users(
    q: str | None = None,
    role: Role | None = None,
    vendor_id: int | None = None,
    status_: ActiveStatus | None = Query(default=None, alias="status"),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
    _: User = Depends(require_permission("user:read")),
    scope: VendorScope = Depends(get_vendor_scope),
    db: Session = Depends(get_db),
):
    cond = []
    if not scope.is_global:
        cond.append(User.vendor_id == scope.vendor_id)
    elif vendor_id:
        cond.append(User.vendor_id == vendor_id)
    if role:
        cond.append(User.role == role)
    if status_:
        cond.append(User.status == status_)
    if q:
        like = f"%{q.strip()}%"
        cond.append(or_(User.username.ilike(like), User.email.ilike(like),
                        User.first_name.ilike(like), User.last_name.ilike(like)))
    total = db.scalar(select(func.count()).select_from(User).where(*cond))
    rows = db.execute(
        select(User, Vendor.name).outerjoin(Vendor, Vendor.id == User.vendor_id)
        .where(*cond).order_by(User.created_at.desc(), User.id.desc()).limit(limit).offset(offset)
    ).all()
    names = dict(db.execute(select(Customer.id, Customer.name).where(Customer.id.in_({u.customer_id for u, _ in rows if u.customer_id}))).all())
    return {"total": total, "items": [_out(u, vn, names.get(u.customer_id)) for u, vn in rows]}


@router.get("/{user_id}", response_model=UserOut)
def get_user(
    user_id: int, _: User = Depends(require_permission("user:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    u = _get_scoped(db, scope, user_id)
    return _out(u, _vendor_name(db, u.vendor_id), _customer_name(db, u.customer_id))


@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, body: UserUpdate, actor: User = Depends(require_any_permission("user:write", "user:manage")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    u = _get_scoped(db, scope, user_id)
    _ensure_manageable(actor, u)
    changes = body.model_dump(exclude_unset=True)
    if "email" in changes and changes["email"]:
        email = str(changes["email"]).lower()
        if db.scalar(select(User.id).where(func.lower(User.email) == email, User.id != u.id)):
            raise _field_error("email", "Email is already in use")
        changes["email"] = email
    if "customer_id" in changes and u.role != Role.OPERATOR and changes["customer_id"] is None:
        del changes["customer_id"]
    if "customer_id" in changes:
        if u.role != Role.OPERATOR:
            raise _field_error("customer_id", "Only Operators are tagged to a customer")
        _check_customer(db, u.vendor_id, changes["customer_id"])
    for k, v in changes.items():
        setattr(u, k, v)
    audit.record(db, "user.updated", actor, entity_type="user", entity_id=u.id, vendor_id=u.vendor_id,
                 detail={"fields": sorted(changes)})
    db.commit()
    return _out(u, _vendor_name(db, u.vendor_id), _customer_name(db, u.customer_id))


@router.patch("/{user_id}/status", response_model=UserOut)
def set_status(
    user_id: int, body: StatusIn, actor: User = Depends(require_any_permission("user:write", "user:manage")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    u = _get_scoped(db, scope, user_id)
    _ensure_manageable(actor, u)
    if u.id == actor.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot change your own status")
    u.status = body.status
    if body.status == ActiveStatus.INACTIVE:
        u.token_version += 1  # drop live sessions immediately
    action = "user.activated" if body.status == ActiveStatus.ACTIVE else "user.deactivated"
    audit.record(db, action, actor, entity_type="user", entity_id=u.id, vendor_id=u.vendor_id)
    db.commit()
    return _out(u, _vendor_name(db, u.vendor_id), _customer_name(db, u.customer_id))


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int, actor: User = Depends(require_permission("user:write")),  # Super Admin only
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    """Permanently removes a user who has no history. Anyone who has created trips/expenses, assigned drivers, etc.
    is referenced by that (append-only) history and cannot be deleted — deactivate them instead."""
    u = _get_scoped(db, scope, user_id)
    if u.id == actor.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You cannot delete your own account")
    if u.role == Role.SUPER_ADMIN:
        raise HTTPException(status.HTTP_409_CONFLICT, "Super Admin accounts cannot be deleted")
    snapshot = {"username": u.username, "email": u.email, "role": u.role.value}
    vendor_id = u.vendor_id
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == u.id))
    db.execute(update(EmailLog).where(EmailLog.user_id == u.id).values(user_id=None))  # keep the delivery record
    try:
        db.delete(u)
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This user has activity history (trips, expenses or audit records) and cannot be deleted. "
                            "Deactivate them instead.")
    audit.record(db, "user.deleted", actor, entity_type="user", entity_id=user_id, vendor_id=vendor_id, detail=snapshot)
    db.commit()


@router.post("/{user_id}/resend-onboarding", response_model=OnboardingResult)
def resend_onboarding(
    user_id: int, actor: User = Depends(require_any_permission("user:write", "user:manage")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    u = _get_scoped(db, scope, user_id)
    _ensure_manageable(actor, u)
    if u.initial_setup_completed_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "This user has already set a password. They can use 'Forgot password'.")
    temp, link = _issue_credentials(db, u)  # old temp password is replaced, so it can't be recovered/re-sent
    audit.record(db, "user.onboarding_resent", actor, entity_type="user", entity_id=u.id, vendor_id=u.vendor_id)
    email_status = _send_onboarding(db, u, link)
    db.commit()
    return OnboardingResult(user=_out(u, _vendor_name(db, u.vendor_id), _customer_name(db, u.customer_id)), temporary_password=temp,
                            temp_password_expires_at=u.temp_password_expires_at, email_status=email_status)
