from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .revisions import Revision, window_for
from .windows import Window


@dataclass(frozen=True)
class PlannedOccurrence:
    scheduled_date: date
    timezone: str
    window: Window


@dataclass
class GenerationPlan:
    occurrences: list[PlannedOccurrence] = field(default_factory=list)
    through: date | None = (
        None  # Latest date successfully covered by this generation plan
    )
    horizon: date | None = None  # Target end date of the current generation window.
    gap_days: int = 0  # Number of older dates skipped because they fall outside the configured look-back limit.
    more: bool = False  # Indicates that additional generation batches are required to reach the target horizon.


def plan_generation(
    *,
    today: date,
    generated_through: date | None,
    revisions: Sequence[Revision],
    horizon_days: int = 6,
    batch_days: int = 31,
    max_lookback_days: int = 60,
) -> GenerationPlan:
    if not revisions:
        return GenerationPlan()
    horizon = today + timedelta(days=horizon_days)
    start = (
        generated_through + timedelta(days=1)
        if generated_through is not None
        else min(r.effective_from for r in revisions)
    )  # if previously generated then take the next day as generation start and if this is the first time generating then which ever revision date is min pick that so that nothing is skipped
    floor = today - timedelta(
        days=max_lookback_days
    )  # set the allowed lookback boundary if worker is offline
    gap = 0
    if start < floor:
        gap = (floor - start).days
        start = floor  # move the start date forward to the maximum allowed lookback boundary
    if start > horizon:  # handle activities that start in the future
        return GenerationPlan(
            through=horizon, horizon=horizon, gap_days=gap, more=False
        )
    end = min(horizon, start + timedelta(days=batch_days - 1))
    plan = GenerationPlan(
        through=end, horizon=horizon, gap_days=gap, more=end < horizon
    )
    d = start
    while d <= end:
        planned = window_for(revisions, d)
        if planned is not None:
            rev, w = planned
            plan.occurrences.append(PlannedOccurrence(d, rev.timezone, w))
            d += timedelta(days=1)
    return plan
