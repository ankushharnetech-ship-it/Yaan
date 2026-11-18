"""Email adapter layer. Providers, in priority order: AWS SES, Zoho ZeptoMail API, SMTP (Zoho Mail etc.), SendGrid; the console provider is dev-only."""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from datetime import datetime, timezone
from typing import Protocol

import httpx
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import EmailLog
from app.services import email_templates as tpl

log = logging.getLogger("yaan.email")


class EmailProvider(Protocol):
    def send(self, to: str, subject: str, text: str, html: str | None = None, to_name: str | None = None) -> str | None:
        """Returns provider message id. Raises on failure."""


class ConsoleEmailProvider:
    def send(self, to, subject, text, html=None, to_name=None):
        log.warning("DEV EMAIL to=%s subject=%s\n%s", to, subject, text)
        return "console"


class SendGridEmailProvider:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def send(self, to, subject, text, html=None, to_name=None):
        s = get_settings()
        content = [{"type": "text/plain", "value": text}]
        if html:
            content.append({"type": "text/html", "value": html})
        r = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "personalizations": [{"to": [{"email": to, **({"name": to_name} if to_name else {})}]}],
                "from": {"email": s.email_from, "name": s.email_from_name},
                "subject": subject,
                "content": content,
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.headers.get("X-Message-Id")


class ZeptoMailEmailProvider:
    """Zoho ZeptoMail transactional email API (the key is sent as 'Zoho-enczapikey <token>')."""

    def __init__(self, api_key: str):
        self.api_key = api_key.strip()
        # Accept the token with or without the 'Zoho-enczapikey ' prefix.
        if self.api_key.lower().startswith("zoho-enczapikey"):
            self.api_key = self.api_key.split(None, 1)[1] if " " in self.api_key else ""

    def send(self, to, subject, text, html=None, to_name=None):
        s = get_settings()
        payload = {
            "from": {"address": s.email_from, "name": s.email_from_name},
            "to": [{"email_address": {"address": to, **({"name": to_name} if to_name else {})}}],
            "subject": subject,
            "textbody": text,
        }
        if html:
            payload["htmlbody"] = html
        r = httpx.post(
            s.zeptomail_api_url,
            headers={"accept": "application/json", "content-type": "application/json",
                     "authorization": f"Zoho-enczapikey {self.api_key}"},
            json=payload,
            timeout=15,
        )
        if r.status_code >= 400:  # surface ZeptoMail's reason (bad token, unverified sender domain, ...) in the email log
            raise RuntimeError(f"ZeptoMail {r.status_code}: {r.text[:300]}")
        try:
            return r.json().get("request_id") or (r.json().get("data") or [{}])[0].get("message_id")
        except Exception:
            return None


class SesEmailProvider:
    def send(self, to, subject, text, html=None, to_name=None):
        import boto3  # imported here so the app still starts where SES is not used

        s = get_settings()
        client = boto3.client("sesv2", region_name=s.aws_ses_region, aws_access_key_id=s.aws_access_key_id or None,
                              aws_secret_access_key=s.aws_secret_access_key or None)
        body = {"Text": {"Data": text, "Charset": "UTF-8"}}
        if html:
            body["Html"] = {"Data": html, "Charset": "UTF-8"}
        extra = {"ConfigurationSetName": s.aws_ses_configuration_set} if s.aws_ses_configuration_set else {}
        r = client.send_email(
            FromEmailAddress=f"{s.email_from_name} <{s.email_from}>", Destination={"ToAddresses": [formataddr((to_name, to)) if to_name else to]},
            Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"}, "Body": body}}, **extra)
        return r.get("MessageId")


class SmtpEmailProvider:
    def send(self, to, subject, text, html=None, to_name=None):
        s = get_settings()
        msg = EmailMessage()
        msg["From"] = f"{s.email_from_name} <{s.email_from}>"
        msg["To"], msg["Subject"] = (formataddr((to_name, to)) if to_name else to), subject
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        ctx = ssl.create_default_context()
        if s.smtp_use_ssl:
            server = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ctx)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15)
        with server:
            if not s.smtp_use_ssl:
                server.starttls(context=ctx)
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password or "")
            server.send_message(msg)
        return "smtp"


def get_provider() -> EmailProvider:
    s = get_settings()
    if s.aws_ses_region:
        return SesEmailProvider()
    if s.zeptomail_api_key:
        return ZeptoMailEmailProvider(s.zeptomail_api_key)
    if s.smtp_host:  # Zoho Mail (or any SMTP server) — preferred over SendGrid when configured
        return SmtpEmailProvider()
    if s.sendgrid_api_key:
        return SendGridEmailProvider(s.sendgrid_api_key)
    return ConsoleEmailProvider()


def send_and_log(
    db: Session, *, to: str, subject: str, text: str, template: str,
    user_id: int | None = None, vendor_id: int | None = None, html: str | None = None, to_name: str | None = None,
) -> EmailLog:
    """Sends an email and records the outcome independently of the caller's business result."""
    entry = EmailLog(user_id=user_id, vendor_id=vendor_id, to_email=to, template=template, status="pending")
    db.add(entry)
    db.flush()
    try:
        entry.provider_message_id = get_provider().send(to, subject, text, html, to_name=to_name)
        entry.status = "sent"
        entry.sent_at = datetime.now(timezone.utc)
    except Exception as exc:  # provider failure must not break onboarding
        entry.status = "failed"
        entry.failure_reason = str(exc)[:500]
        log.exception("email send failed")
    return entry


def _full_name(first: str, last: str = "") -> str:
    return f"{first} {last}".strip()


def onboarding_email(first_name: str, username: str, expires_at: datetime, link: str, *, last_name: str = "",
                     role: str = "") -> tuple[str, str, str]:
    """(subject, text, html). Never contains a password – only the username and a single-use set-password link."""
    s = get_settings()
    text, html = tpl.onboarding(_full_name(first_name, last_name), username, role.replace("_", " ").title() or "User",
                                f"{expires_at:%d %b %Y, %H:%M UTC}", s.temp_password_days, link)
    return "Welcome to YAAN — set your password", text, html


def reset_email(first_name: str, link: str, minutes: int, *, last_name: str = "") -> tuple[str, str, str]:
    text, html = tpl.password_reset(_full_name(first_name, last_name), minutes, link)
    return "YAAN password reset", text, html
