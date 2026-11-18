from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin
from app.models.enums import ActiveStatus, Role, str_enum


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (
        # Every role except Super Admin is vendor-scoped (spec 2.1 / 20).
        CheckConstraint(
            "(role = 'super_admin' AND vendor_id IS NULL) OR "
            "(role <> 'super_admin' AND vendor_id IS NOT NULL)",
            name="ck_users_vendor_scope",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    middle_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    mobile: Mapped[str | None] = mapped_column(String(20))
    gender: Mapped[str | None] = mapped_column(String(20))
    address: Mapped[str | None] = mapped_column(Text)

    role: Mapped[Role] = mapped_column(str_enum(Role), nullable=False)
    vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id"), index=True)
    status: Mapped[ActiveStatus] = mapped_column(
        str_enum(ActiveStatus), default=ActiveStatus.ACTIVE, nullable=False
    )

    # A Driver login is linked to exactly one driver master record (enforced by the API + unique index)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), unique=True)
    # An Operator is a customer-company user: tagged to exactly one customer of the vendor (None for every other role)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)

    # Credentials – only hashes are stored, never plaintext (spec 2.1.7)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    temp_password_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    initial_setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Bumped on password change/reset so previously issued tokens stop working
    token_version: Mapped[int] = mapped_column(default=0, server_default="0", nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
