"""SMS adapter layer. Twilio is the chosen provider; the console provider is dev-only."""
import base64
import hashlib
import hmac
import logging
import re
from typing import Protocol

import httpx

from app.core.config import get_settings

log = logging.getLogger("yaan.sms")


class SmsProvider(Protocol):
    def send(self, to: str, body: str, status_callback: str | None = None) -> str:
        """Returns the provider's message id. Raises SmsError on failure."""


class SmsError(Exception):
    pass


class ConsoleSmsProvider:
    def send(self, to, body, status_callback=None):
        log.warning("DEV SMS to=%s\n%s", to, body)
        return "console"


class TwilioSmsProvider:
    def __init__(self, sid: str, token: str, from_number: str):
        self.sid, self.token, self.from_number = sid, token, from_number

    def send(self, to, body, status_callback=None):
        data = {"To": to, "From": self.from_number, "Body": body}
        if status_callback:
            data["StatusCallback"] = status_callback
        try:
            r = httpx.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.sid}/Messages.json",
                data=data, auth=(self.sid, self.token), timeout=get_settings().sms_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise SmsError(f"Could not reach Twilio: {type(exc).__name__}") from exc
        payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code >= 400:
            raise SmsError(f"Twilio {payload.get('code', r.status_code)}: {payload.get('message', 'request failed')}"[:480])
        return payload["sid"]


def get_provider() -> SmsProvider:
    s = get_settings()
    if s.twilio_account_sid and s.twilio_auth_token and s.twilio_from_number:
        return TwilioSmsProvider(s.twilio_account_sid, s.twilio_auth_token, s.twilio_from_number)
    return ConsoleSmsProvider()


def status_callback_url() -> str | None:
    base = get_settings().public_base_url
    return f"{base.rstrip('/')}/api/webhooks/twilio/status" if base else None


def normalize_phone(raw: str | None) -> str | None:
    """To E.164. Local numbers get DEFAULT_COUNTRY_CODE. Returns None when it can't be a valid number."""
    if not raw:
        return None
    s = re.sub(r"[\s\-().]", "", raw.strip())
    if s.startswith("00"):
        s = "+" + s[2:]
    if not s.startswith("+"):
        s = s.lstrip("0")
        s = get_settings().default_country_code + s
    return s if re.fullmatch(r"\+[1-9]\d{7,14}", s) else None


def valid_twilio_signature(url: str, params: dict[str, str], signature: str) -> bool:
    """Twilio signs url + sorted(key+value) with HMAC-SHA1 using the auth token."""
    token = get_settings().twilio_auth_token
    if not token or not signature:
        return False
    data = url + "".join(k + params[k] for k in sorted(params))
    expected = base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(expected, signature)
