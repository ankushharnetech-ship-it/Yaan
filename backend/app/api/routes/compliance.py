from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import Body, StatusBody, check_lookup, field_error
from app.api.deps import VendorScope, get_vendor_scope, require_permission
from app.db.session import get_db
from app.models import ActiveStatus, ComplianceItem, Driver, Role, User, Vehicle
from app.services import audit, compliance as svc

router = APIRouter(prefix="/compliance", tags=["compliance"])
Subject = Literal["drivers", "vehicles"]


class ItemIn(Body):
    subject_type: Literal["driver", "vehicle"] | None = None  # required on create; immutable afterwards
    driver_id: int | None = None
    vehicle_id: int | None = None
    doc_type_id: int
    title: str | None = Field(default=None, max_length=120)
    reference_number: str | None = Field(default=None, max_length=100)
    issue_date: date | None = None
    expiry_date: date
    notes: str | None = None

    @model_validator(mode="after")
    def _dates(self):
        if self.issue_date and self.expiry_date < self.issue_date:
            raise ValueError("Expiry date cannot be before the issue date")
        return self


def _out(r: svc.Row, names: dict, types: dict) -> dict:
    it = r.item
    sid = it.driver_id if it.subject_type == "driver" else it.vehicle_id
    return {"id": it.id, "vendor_id": it.vendor_id, "subject_type": it.subject_type, "subject_id": sid,
            "subject_name": names.get(sid, "—"), "doc_type_id": it.doc_type_id, "doc_type": types.get(it.doc_type_id),
            "title": it.title, "reference_number": it.reference_number, "issue_date": it.issue_date,
            "expiry_date": it.expiry_date, "days_left": r.days_left, "compliance": r.state, "notes": it.notes,
            "status": it.status.value}


def _names(db: Session, subject: str, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    if subject == "driver":
        return {d.id: f"{d.first_name} {d.last_name}" for d in db.scalars(select(Driver).where(Driver.id.in_(ids)))}
    return {v.id: v.vehicle_number for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(ids)))}


@router.get("/{subject}")
def list_compliance(
    subject: Subject, status: Literal["valid", "expiring", "expired"] | None = None, doc_type_id: int | None = None,
    subject_id: int | None = None, q: str | None = None, vendor_id: int | None = None, include_retired: bool = False,
    limit: int = Query(25, ge=1, le=200), offset: int = Query(0, ge=0),
    user: User = Depends(require_permission("compliance:read")),
    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db),
):
    one = "driver" if subject == "drivers" else "vehicle"
    own_driver: int | None = None
    if user.role == Role.DRIVER:  # drivers see only their own documents
        if one != "driver":
            raise HTTPException(403, "You do not have permission to do this")
        own_driver = user.driver_id or -1
    vid = scope.vendor_id if not scope.is_global else vendor_id
    rows = svc.load(db, one, vid, own_driver, doc_type_id=doc_type_id, subject_id=subject_id, include_retired=include_retired)
    subjects = svc.subject_rollup(db, one, [r for r in rows if r.item.status == ActiveStatus.ACTIVE], vid, own_driver, subject_id)

    live = [r for r in rows if r.item.status == ActiveStatus.ACTIVE]
    count = lambda s: sum(r.state == s for r in live)  # noqa: E731
    states = [s["state"] for s in subjects]
    summary = {
        "documents": {"total": len(live), "valid": count("valid"), "expiring": count("expiring"), "expired": count("expired")},
        "subjects": {"total": len(subjects), "compliant": states.count("compliant"), "expiring": states.count("expiring"),
                     "non_compliant": states.count("non_compliant"), "no_documents": states.count("no_documents")},
    }
    names = _names(db, one, {r.item.driver_id if one == "driver" else r.item.vehicle_id for r in rows})
    types = svc.doc_type_names(db, f"{one}_doc_type")
    shown = [r for r in rows if (not status or r.state == status)]
    if q:
        needle = q.strip().lower()
        shown = [r for r in shown if needle in (names.get(r.item.driver_id or r.item.vehicle_id, "") + " " +
                                                (r.item.reference_number or "") + " " + (r.item.title or "") + " " +
                                                types.get(r.item.doc_type_id, "")).lower()]
    return {"summary": summary, "subjects": subjects, "total": len(shown),
            "items": [_out(r, names, types) for r in shown[offset: offset + limit]]}


def _validate(db: Session, scope: VendorScope, body: ItemIn, existing: ComplianceItem | None):
    st = existing.subject_type if existing else body.subject_type
    if st is None:
        raise field_error("subject_type", "Choose driver or vehicle")
    if existing is None:
        if st == "driver":
            if body.driver_id is None or body.vehicle_id is not None:
                raise field_error("driver_id", "Select a driver")
            subj = db.get(Driver, body.driver_id)
        else:
            if body.vehicle_id is None or body.driver_id is not None:
                raise field_error("vehicle_id", "Select a vehicle")
            subj = db.get(Vehicle, body.vehicle_id)
        if subj is None:
            raise HTTPException(404, "Not found")
        scope.ensure(subj.vendor_id)
    elif body.subject_type not in (None, st) or (body.driver_id and body.driver_id != existing.driver_id) \
            or (body.vehicle_id and body.vehicle_id != existing.vehicle_id):
        raise field_error("subject_type", "A document cannot be moved to another driver or vehicle")
    check_lookup(db, body.doc_type_id, f"{st}_doc_type", "doc_type_id", required=True)
    return st


@router.post("/items", status_code=201)
def create_item(body: ItemIn, actor: User = Depends(require_permission("compliance:write")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    st = _validate(db, scope, body, None)
    subj = db.get(Driver, body.driver_id) if st == "driver" else db.get(Vehicle, body.vehicle_id)
    it = ComplianceItem(vendor_id=subj.vendor_id, subject_type=st, driver_id=body.driver_id, vehicle_id=body.vehicle_id,
                        **body.model_dump(include={"doc_type_id", "title", "reference_number", "issue_date", "expiry_date", "notes"}))
    db.add(it)
    db.flush()
    audit.record(db, "compliance.created", actor, entity_type="compliance", entity_id=it.id, vendor_id=it.vendor_id,
                 detail={"subject": st, "expiry": it.expiry_date.isoformat()})
    db.commit()
    return _single(db, it)


def _single(db: Session, it: ComplianceItem) -> dict:
    one = it.subject_type
    rows = [r for r in svc.load(db, one, it.vendor_id, include_retired=True) if r.item.id == it.id]
    return _out(rows[0], _names(db, one, {it.driver_id or it.vehicle_id}), svc.doc_type_names(db, f"{one}_doc_type"))


def _get(db: Session, scope: VendorScope, item_id: int) -> ComplianceItem:
    it = db.get(ComplianceItem, item_id)
    if it is None:
        raise HTTPException(404, "Not found")
    scope.ensure(it.vendor_id)
    return it


@router.put("/items/{item_id}")
def update_item(item_id: int, body: ItemIn, actor: User = Depends(require_permission("compliance:write")),
                scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    it = _get(db, scope, item_id)
    _validate(db, scope, body, it)
    for k in ("doc_type_id", "title", "reference_number", "issue_date", "expiry_date", "notes"):
        setattr(it, k, getattr(body, k))
    audit.record(db, "compliance.updated", actor, entity_type="compliance", entity_id=it.id, vendor_id=it.vendor_id,
                 detail={"expiry": it.expiry_date.isoformat()})
    db.commit()
    return _single(db, it)


@router.patch("/items/{item_id}/status")
def set_item_status(item_id: int, body: StatusBody, actor: User = Depends(require_permission("compliance:write")),
                    scope: VendorScope = Depends(get_vendor_scope), db: Session = Depends(get_db)):
    """Inactive = retired/superseded (e.g. replaced by a renewed document). Never deleted."""
    it = _get(db, scope, item_id)
    it.status = body.status
    audit.record(db, f"compliance.{'activated' if body.status == ActiveStatus.ACTIVE else 'retired'}", actor,
                 entity_type="compliance", entity_id=it.id, vendor_id=it.vendor_id)
    db.commit()
    return _single(db, it)
