from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Window:
    start: datetime  # UTC
    end: datetime  # UTC

    @property
    def hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def day_window(tz: str, d: date) -> Window | None:
    """Return the UTC window for local date `d`, or None when the date does not exist in `tz`"""
    zone = ZoneInfo(tz)
    start = datetime.combine(d, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(d + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    if end <= start:
        return None  # prevents creating an occurrence for a date which has no valid time window
    return Window(start, end)


def local_date_of(instant: datetime, tz: str) -> date:
    """The local calendar date in provided `tz`"""
    return instant.astimezone(ZoneInfo(tz)).date()
