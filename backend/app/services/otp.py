"""Drop-off OTPs.

Nothing readable is stored. Each passenger row keeps a random `otp_seed`; the OTP is
    HMAC-SHA256(server secret, "otp:<trip>:<employee>:<seed>")  ->  last N digits.
So the database alone (a backup, a DBA, a SQL injection read) does not reveal any OTP, yet the app can show it to the
one person allowed to see it (the requesting Operator) and verify what the driver types. A new seed = a new OTP.
"""
import hashlib
import hmac
import secrets

from app.core.config import get_settings

TOKEN = "[OTP]"  # placeholder kept in stored notification text; replaced with the real code only at send time
MASK = "••••"


def new_seed() -> str:
    return secrets.token_hex(16)


def code(seed: str, trip_id: int, employee_id: int) -> str:
    s = get_settings()
    digest = hmac.new(s.jwt_secret.encode(), f"otp:{trip_id}:{employee_id}:{seed}".encode(), hashlib.sha256).digest()
    return str(int.from_bytes(digest[:8], "big") % (10 ** s.otp_length)).zfill(s.otp_length)


def matches(seed: str, trip_id: int, employee_id: int, supplied: str) -> bool:
    return hmac.compare_digest(code(seed, trip_id, employee_id), (supplied or "").strip())


def reveal(text: str, seed: str | None, trip_id: int | None, employee_id: int | None) -> str:
    """Real text to send: swaps the token for the code (or leaves a mask if there is no OTP to give)."""
    if TOKEN not in text:
        return text
    if not seed or trip_id is None or employee_id is None:
        return text.replace(TOKEN, MASK)
    return text.replace(TOKEN, code(seed, trip_id, employee_id))


def mask(text: str | None) -> str | None:
    """What screens and API responses show for a stored notification."""
    return text.replace(TOKEN, MASK) if text else text
