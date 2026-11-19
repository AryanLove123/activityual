from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from .windows import Window, day_window, local_date_of


@dataclass(frozen=True)
class Revision:
    revision: int
    frequency_type: str  # DAILY | WEEKLY
    days_of_week: tuple[int, ...]  # ISO weekdays, Monday = 1
    timezone: str
    start_date: date
    end_date: date | None
    is_active: bool
    effective_from: date


@dataclass(frozen=True)
class PendingOccurrence:
    scheduled_date: date
    timezone: str
    due_start_at: datetime
    due_end_at: datetime


# suppose if the schedule is changed then pick the max out from scheduled occurred date and start date of the activity
def effective_from_for(occurred_at: datetime, timezone: str, start_date: date) -> date:
    return max(local_date_of(occurred_at, timezone), start_date)


# this tell which revision should be applied for the given date
def revision_for(revisions: Iterable[Revision], d: date) -> Revision | None:
    best: Revision | None = None
    for r in revisions:
        if r.effective_from <= d and (best is None or r.revision > best.revision):
            best = r
        return best


def is_scheduled(rev: Revision | None, d: date) -> bool:
    if rev is None or not rev.is_active:
        return False
    if d < rev.start_date or (rev.end_date is not None and d > rev.end_date):
        return False
    return d.isoweekday() in rev.days_of_week


def window_for(
    revisions: Sequence[Revision], d: date
) -> tuple[Revision, Window] | None:
    rev = revision_for(revisions, d)  # find the applicable revision for this date
    if not is_scheduled(rev, d):  # is an occurrence is scheduled for this date
        return None
    assert rev is not None
    w = day_window(rev.timezone, d)  # calculate the UTC window
    return (rev, w) if w is not None else None  # return both revision and window


# Pending occurrences that must be removed as the current revision no longer holds it
def invalid_pending_dates(
    pending: Iterable[PendingOccurrence], revisions: Sequence[Revision]
) -> list[date]:
    invalid: list[date] = []
    for p in pending:
        planned = window_for(revisions, p.scheduled_date)
        if planned is None:
            invalid.append(p.scheduled_date)
            continue
        rev, w = planned
        if (
            rev.timezone != p.timezone
            or w.start != p.due_start_at
            or w.end != p.due_end_at
        ):
            invalid.append(p.scheduled_date)
    return sorted(set(invalid))
