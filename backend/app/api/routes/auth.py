from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_user_allow_pending
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.db.session import get_db
from app.models import ActiveStatus, Customer, User, Vendor
from app.schemas import ChangePasswordIn, ForgotIn, LoginIn, LoginOut, ResetIn, UserMe
from app.services import audit, auth_service as svc, email as mail

router = APIRouter(prefix="/auth", tags=["auth"])

_DUMMY_HASH = hash_password("not-a-real-password")  # equalises timing for unknown usernames


def _me(u: User, db: Session | None = None) -> UserMe:
    cust = db.get(Customer, u.customer_id) if db is not None and u.customer_id else None
    return UserMe(
        id=u.id, username=u.username, first_name=u.first_name, last_name=u.last_name, email=u.email,
        role=u.role, vendor_id=u.vendor_id, customer_id=u.customer_id, customer_name=cust.name if cust else None,
        must_change_password=u.initial_setup_completed_at is None,
    )


def _token(u: User) -> str:
    return create_access_token(u.id, {"tv": u.token_version})


@router.post("/login", response_model=LoginOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    uname = body.username.strip().lower()
    ip = request.client.host if request.client else "?"
    svc.limiter.check(f"login:{ip}:{uname}", s.login_max_attempts, s.login_window_seconds)

    user = db.scalar(select(User).where(func.lower(User.username) == uname))
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok or user.status != ActiveStatus.ACTIVE:
        audit.record(db, "auth.login_failed", user, detail={"username": uname})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password")

    if user.vendor_id is not None:
        vendor = db.get(Vendor, user.vendor_id)
        if vendor is None or vendor.status != ActiveStatus.ACTIVE:
            audit.record(db, "auth.login_blocked_vendor_inactive", user)
            db.commit()
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Your organisation's account is inactive. Please contact your administrator.",
            )

    if svc.temp_password_expired(user):
        audit.record(db, "auth.login_blocked_temp_expired", user)
        db.commit()
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Your temporary password has expired. Use 'Forgot password' to set a new one.",
        )

    user.last_login_at = svc.now()
    audit.record(db, "auth.login", user)
    db.commit()
    return LoginOut(access_token=_token(user), user=_me(user, db))


@router.post("/logout", status_code=204)
def logout(user: User = Depends(get_user_allow_pending), db: Session = Depends(get_db)):
    # Tokens are short-lived and stateless; the client discards it. Audited for the trail.
    audit.record(db, "auth.logout", user)
    db.commit()


@router.post("/forgot-password")
def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    ident = body.identifier.strip().lower()
    ip = request.client.host if request.client else "?"
    svc.limiter.check(f"forgot:{ip}", s.login_max_attempts, s.login_window_seconds)

    user = db.scalar(
        select(User).where(or_(func.lower(User.username) == ident, func.lower(User.email) == ident))
    )
    if user and user.status == ActiveStatus.ACTIVE:
        raw = svc.create_reset_token(db, user, s.reset_token_minutes)
        subject, text, html = mail.reset_email(
            user.first_name, f"{s.frontend_url}/reset-password?token={raw}", s.reset_token_minutes, last_name=user.last_name
        )
        audit.record(db, "auth.forgot_password", user)
        mail.send_and_log(db, to=user.email, subject=subject, text=text, html=html,
                          to_name=f"{user.first_name} {user.last_name}".strip(), template="password_reset",
                          user_id=user.id, vendor_id=user.vendor_id)
        db.commit()
    # Same response whether or not the account exists (no user enumeration)
    return {"message": "If an account matches, a reset link has been emailed."}


@router.post("/reset-password")
def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    svc.limiter.check(f"reset:{request.client.host if request.client else '?'}", s.login_max_attempts, s.login_window_seconds)
    svc.validate_password_strength(body.new_password)
    user = svc.consume_reset_token(db, body.token)
    if user.status != ActiveStatus.ACTIVE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    svc.set_new_password(user, body.new_password)
    audit.record(db, "auth.password_reset", user)
    db.commit()
    return {"message": "Password updated. You can now sign in."}


@router.post("/change-password", response_model=LoginOut)
def change_password(
    body: ChangePasswordIn, user: User = Depends(get_user_allow_pending), db: Session = Depends(get_db)
):
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            422,
            detail=[{"loc": ["body", "current_password"], "msg": "Current password is incorrect"}],
        )
    if body.current_password == body.new_password:
        raise HTTPException(
            422,
            detail=[{"loc": ["body", "new_password"], "msg": "Choose a password different from the current one"}],
        )
    svc.validate_password_strength(body.new_password)
    first_time = user.initial_setup_completed_at is None
    svc.set_new_password(user, body.new_password)
    audit.record(db, "auth.password_changed", user, detail={"initial_setup": first_time})
    db.commit()
    return LoginOut(access_token=_token(user), user=_me(user, db))


@router.get("/me", response_model=UserMe)
def me(user: User = Depends(get_user_allow_pending), db: Session = Depends(get_db)):
    return _me(user, db)
