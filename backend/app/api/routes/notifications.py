from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.core.config import get_settings
from app.db.session import get_db
import re

from app.models import EmailLog, Role, SmsLog, User
from app.services import audit, notifications, otp, sms

router = APIRouter(tags=["notifications"])


def _out(r: SmsLog) -> dict:
    iso = lambda d: d.astimezone(timezone.utc).isoformat() if d else None  # noqa: E731
    return {"id": r.id, "trip_id": r.trip_id, "recipient_type": r.recipient_type, "recipient_name": r.recipient_name,
            "phone": r.phone, "template": r.template, "body": otp.mask(r.body), "status": r.status,  # OTPs are never shown in logs
            "failure_reason": r.failure_reason, "attempts": r.attempts, "created_at": iso(r.created_at),
            "sent_at": iso(r.sent_at), "delivered_at": iso(r.delivered_at)}


def _scope_cond(user: User, scope: VendorScope):
    if user.role == Role.DRIVER:  # drivers see only the messages sent to them
        return [SmsLog.recipient_type == "driver", SmsLog.driver_id == (user.driver_id or -1)]
    return [] if scope.is_global else [SmsLog.vendor_id == scope.vendor_id]


@router.get("/sms-logs")
def list_sms_logs(
    trip_id: int | None = None, status: str | None = None, recipient_type: str | None = None, q: str | None = None,
    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("notification:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = _scope_cond(user, scope)
    if trip_id:
        cond.append(SmsLog.trip_id == trip_id)
    if status:
        cond.append(SmsLog.status == status)
    if recipient_type:
        cond.append(SmsLog.recipient_type == recipient_type)
    if q:
        cond.append(or_(SmsLog.phone.ilike(f"%{q}%"), SmsLog.recipient_name.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(SmsLog).where(*cond))
    rows = db.scalars(select(SmsLog).where(*cond).order_by(SmsLog.created_at.desc(), SmsLog.id.desc())
                      .limit(limit).offset(offset)).all()
    return {"total": total, "items": [_out(r) for r in rows]}


@router.post("/sms-logs/{log_id}/retry")
def retry_sms(log_id: int, background: BackgroundTasks, actor: User = Depends(require_permission("trip:edit")),
              scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    row = db.get(SmsLog, log_id)
    if row is None:
        raise HTTPException(404, "Not found")
    scope.ensure(row.vendor_id)
    if row.status != "failed":
        raise HTTPException(409, "Only failed messages can be retried")
    phone = sms.normalize_phone(row.phone)
    if phone is None:
        raise HTTPException(422, "The recipient's phone number is invalid. Correct it on the driver/employee record first.")
    row.phone = phone
    notifications.mark_for_retry(db, row)
    audit.record(db, "sms.retry", actor, entity_type="sms", entity_id=row.id, vendor_id=row.vendor_id)
    db.commit()
    background.add_task(notifications.deliver, ([row.id], []))
    return _out(row)


# ---- Email notifications (trip emails to employees/drivers; account/reset emails are not listed here) ----
def _email_out(r: EmailLog) -> dict:
    iso = lambda d: d.astimezone(timezone.utc).isoformat() if d else None  # noqa: E731
    return {"id": r.id, "trip_id": r.trip_id, "recipient_type": r.recipient_type, "recipient_name": r.recipient_name,
            "email": r.to_email, "subject": r.subject, "template": r.template, "body": otp.mask(r.body), "status": r.status,
            "failure_reason": r.failure_reason, "attempts": r.attempts, "created_at": iso(r.created_at), "sent_at": iso(r.sent_at)}


@router.get("/email-logs")
def list_email_logs(
    trip_id: int | None = None, status: str | None = None, recipient_type: str | None = None, q: str | None = None,
    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("notification:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    cond = [EmailLog.trip_id.is_not(None)]
    if user.role == Role.DRIVER:
        cond += [EmailLog.recipient_type == "driver", EmailLog.driver_id == (user.driver_id or -1)]
    elif not scope.is_global:
        cond.append(EmailLog.vendor_id == scope.vendor_id)
    if trip_id:
        cond.append(EmailLog.trip_id == trip_id)
    if status:
        cond.append(EmailLog.status == status)
    if recipient_type:
        cond.append(EmailLog.recipient_type == recipient_type)
    if q:
        cond.append(or_(EmailLog.to_email.ilike(f"%{q}%"), EmailLog.recipient_name.ilike(f"%{q}%")))
    total = db.scalar(select(func.count()).select_from(EmailLog).where(*cond))
    rows = db.scalars(select(EmailLog).where(*cond).order_by(EmailLog.created_at.desc(), EmailLog.id.desc())
                      .limit(limit).offset(offset)).all()
    return {"total": total, "items": [_email_out(r) for r in rows]}


@router.post("/email-logs/{log_id}/retry")
def retry_email(log_id: int, background: BackgroundTasks, actor: User = Depends(require_permission("trip:edit")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    row = db.get(EmailLog, log_id)
    if row is None or row.trip_id is None:
        raise HTTPException(404, "Not found")
    scope.ensure(row.vendor_id)
    if row.status != "failed":
        raise HTTPException(409, "Only failed messages can be retried")
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", row.to_email or ""):
        raise HTTPException(422, "The recipient's email address is missing or invalid. Correct it on the driver/employee record first.")
    notifications.mark_for_retry(db, row)
    audit.record(db, "email.retry", actor, entity_type="email", entity_id=row.id, vendor_id=row.vendor_id)
    db.commit()
    background.add_task(notifications.deliver, ([], [row.id]))
    return _email_out(row)

# ---- Twilio delivery-status callback (public; authenticated by Twilio's request signature) ----
_STATUS = {"delivered": "delivered", "undelivered": "failed", "failed": "failed", "sent": "sent"}


@router.post("/webhooks/twilio/status", include_in_schema=False)
async def twilio_status(request: Request, db: Session = Depends(get_db)):
    form = {k: str(v) for k, v in (await request.form()).items()}
    url = sms.status_callback_url() or str(request.url)
    if not sms.valid_twilio_signature(url, form, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(403, "Invalid signature")
    new = _STATUS.get(form.get("MessageStatus", ""))
    row = db.scalar(select(SmsLog).where(SmsLog.provider_message_id == form.get("MessageSid")))
    if row and new:
        rank = {"pending": 0, "sent": 1, "delivered": 2, "failed": 2}
        if rank[new] >= rank.get(row.status, 0):  # callbacks can arrive out of order
            row.status = new
            if new == "delivered":
                row.delivered_at = datetime.now(timezone.utc)
            if new == "failed":
                row.failure_reason = f"Carrier error {form.get('ErrorCode', 'unknown')}"
            db.commit()
    return {"ok": True}
