import hashlib
import re
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import PasswordResetToken, User


def now() -> datetime:
    return datetime.now(timezone.utc)


def validate_password_strength(pw: str) -> None:
    min_len = get_settings().password_min_length
    if len(pw) < min_len or not re.search(r"[A-Za-z]", pw) or not re.search(r"\d", pw):
        raise HTTPException(
            422,
            detail=[{"loc": ["body", "new_password"],
                     "msg": f"Use at least {min_len} characters with letters and numbers"}],
        )


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def create_reset_token(db: Session, user: User, minutes: int) -> str:
    """Invalidates any outstanding tokens for the user, returns the raw token (shown once)."""
    for t in db.scalars(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None))
    ):
        t.used_at = now()
    raw = secrets.token_urlsafe(32)
    db.add(PasswordResetToken(user_id=user.id, token_hash=_hash_token(raw), expires_at=now() + timedelta(minutes=minutes)))
    return raw


def consume_reset_token(db: Session, raw: str) -> User:
    bad = HTTPException(status.HTTP_400_BAD_REQUEST, "This link is invalid or has expired")
    tok = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash_token(raw)).with_for_update()
    )
    if tok is None or tok.used_at is not None or tok.expires_at < now():
        raise bad
    tok.used_at = now()
    user = db.get(User, tok.user_id)
    if user is None:
        raise bad
    return user


def set_new_password(user: User, new_password: str) -> None:
    """Replaces any temporary credential, completes first-time setup, kills old sessions."""
    user.password_hash = hash_password(new_password)
    user.temp_password_expires_at = None
    if user.initial_setup_completed_at is None:
        user.initial_setup_completed_at = now()
    user.token_version += 1


def temp_password_expired(user: User) -> bool:
    return (
        user.initial_setup_completed_at is None
        and user.temp_password_expires_at is not None
        and user.temp_password_expires_at < now()
    )


class RateLimiter:
    """In-memory sliding window. Fine for a single instance; swap for Redis when scaling out."""

    def __init__(self):
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, max_hits: int, window: int) -> None:
        t = time.monotonic()
        q = self.hits[key]
        while q and q[0] < t - window:
            q.popleft()
        if len(q) >= max_hits:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Please try again later.")
        q.append(t)

    def reset(self):
        self.hits.clear()


limiter = RateLimiter()
