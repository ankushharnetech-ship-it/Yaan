import enum

from sqlalchemy import Enum


class Role(str, enum.Enum):
    SUPER_ADMIN = "super_admin"
    VENDOR_ADMIN = "vendor_admin"
    OPERATOR = "operator"
    DRIVER = "driver"


class ActiveStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class TripStatus(str, enum.Enum):
    SCHEDULED = "scheduled"  # a request from an Operator, awaiting a Vendor Admin to assign driver + vehicle
    ASSIGNED = "assigned"
    ACCEPTED = "accepted"
    STARTED = "started"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


def str_enum(e: type[enum.Enum], length: int = 30) -> Enum:
    """Enum stored as a plain VARCHAR (no native PG type) – easy to migrate and extend."""
    return Enum(
        e,
        native_enum=False,
        length=length,
        create_constraint=True,
        values_callable=lambda x: [m.value for m in x],
        validate_strings=True,
    )
