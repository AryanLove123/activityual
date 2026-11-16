from datetime import date
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from activityual_common.problems import ProblemError
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Category = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
Notes = Annotated[str, StringConstraints(max_length=1000)]
Frequency = Literal["DAILY", "WEEKLY"]
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]
SCHEDULE_FIELDS = ("frequency_type", "days_of_week", "timezone", "start_date", "end_date", "is_active")

class ActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title
    category: Category = "general"
    notes: Notes = ""
    frequencyType: Frequency
    daysOfWeek: list[Annotated[int, Field(ge=1, le=7)]] | None = None
    timezone: Annotated[str, Field(min_length=1, max_length=64)]
    startDate: date | None = None
    endDate: date | None = None

class ActivityPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Title | None = None
    category: Category | None = None
    notes: Notes | None = None
    frequencyType: Frequency | None = None
    daysOfWeek: list[Annotated[int, Field(ge=1, le=7)]] | None = None
    timezone: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    startDate: date | None = None
    endDate: date | None = None
    isActive: bool | None = None

def field_error(field: str, code: str, message: str) -> dict:
    return {"field": field, "code": code, "message": message}


def validation_problem(errors: list[dict]) -> ProblemError:
    return ProblemError("validation-error", 422, "Request validation failed", errors=errors)


def normalize_days(frequency: str, days: list[int] | None) -> tuple[list[int] | None, list[dict]]:
    errors: list[dict] = []
    if days is not None and len(set(days)) != len(days):
        errors.append(field_error("daysOfWeek", "duplicate_days", "daysOfWeek must not contain duplicates"))
    if frequency == "WEEKLY":
        if not days:
            errors.append(field_error("daysOfWeek", "required_for_weekly", "WEEKLY needs 1-7 weekdays"))
            return None, errors
        return sorted(set(days)), errors
    if days is not None and sorted(set(days)) != ALL_DAYS:
        errors.append(field_error("daysOfWeek", "daily_must_be_all_days", "DAILY activites run every day"))
    return list(ALL_DAYS), errors

def load_zone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except ValueError:
        return None


