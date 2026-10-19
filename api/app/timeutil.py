"""'Today' means today in New York, not on the server's clock."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import settings

TZ = ZoneInfo(settings.timezone)


def now() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    return datetime.now(TZ).date()


def day_bounds(day: date) -> tuple[datetime, datetime]:
    """Start and end of a local calendar day, as UTC instants."""
    start = datetime.combine(day, time.min, tzinfo=TZ)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)
