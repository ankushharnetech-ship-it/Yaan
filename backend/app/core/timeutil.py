from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.core.config import get_settings


def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().business_timezone)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(tz())


def local_date(dt: datetime) -> date:
    return to_local(dt).date()
