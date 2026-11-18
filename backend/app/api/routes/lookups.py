from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models import LookupValue, User

router = APIRouter(prefix="/lookups", tags=["lookups"])


@router.get("")
def all_lookups(_: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Pick-list values grouped by category (vehicle_type, fuel_type, license_type, induction_type, trip_type)."""
    out: dict[str, list[dict]] = {}
    rows = db.scalars(select(LookupValue).where(LookupValue.is_active).order_by(LookupValue.category, LookupValue.sort_order))
    for r in rows:
        out.setdefault(r.category, []).append({"id": r.id, "code": r.code, "label": r.label})
    return out
