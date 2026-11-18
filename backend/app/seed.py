"""DEVELOPMENT-ONLY seed. Never run against production; credentials below are public.

    python -m app.seed
"""
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models import Role, User, Vendor
from app.services.auth_service import now

DEV_PASSWORD = "DevOnly#2026"  # development-only


def main() -> None:
    if get_settings().environment != "development":
        raise SystemExit("Refusing to seed: ENVIRONMENT is not 'development'")
    with SessionLocal() as db:
        if not db.scalar(select(User.id).where(User.username == "superadmin")):
            db.add(User(
                first_name="Super", last_name="Admin", username="superadmin", email="superadmin@yaan.local",
                role=Role.SUPER_ADMIN, password_hash=hash_password(DEV_PASSWORD), initial_setup_completed_at=now(),
            ))
        for code, name in (("VND-A", "Alpha Transport"), ("VND-B", "Bravo Cabs")):
            if not db.scalar(select(Vendor.id).where(Vendor.code == code)):
                db.add(Vendor(code=code, name=name, contact_name="Operations Desk", email=f"{code.lower()}@example.com", address="1 Transport Nagar"))
        db.commit()
    print(f"Seeded. Dev login: superadmin / {DEV_PASSWORD}  (DEVELOPMENT ONLY)")


if __name__ == "__main__":
    main()
