from sqlalchemy.orm import Session

from app.core.request_context import request_id_var
from app.models import AuditLog, User


def record(
    db: Session,
    action: str,
    actor: User | None = None,
    *,
    entity_type: str | None = None,
    entity_id: int | str | None = None,
    vendor_id: int | None = None,
    detail: dict | None = None,
    request_id: str | None = None,
) -> None:
    """Adds an audit row to the caller's transaction (committed with the business change)."""
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor_role=actor.role.value if actor else None,
            vendor_id=vendor_id if vendor_id is not None else (actor.vendor_id if actor else None),
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            detail=detail,
            request_id=request_id or request_id_var.get(),
        )
    )
