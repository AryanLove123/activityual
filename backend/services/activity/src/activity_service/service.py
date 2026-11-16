from datetime import UTC, date, datetime
from uuid import UUID

import sqlalchemy as sa
from activityual_common.events import build_envelope, insert_outbox
from activityual_common.pagination import decode_cursor, encode_cursor
from activityual_common.problems import ProblemError, not_found
from sqlalchemy.orm import Session

from .schemas import (
    SCHEDULE_FIELDS,
    ActivityCreate,
    ActivityPatch,
    field_error,
    load_zone,
    normalize_days,
    validation_problem,
)
from .tables import activity

PRODUCER = "activity-service"


def to_api(row) -> dict:
    return {
        "id": str(row.id),
        "title": row.title,
        "category": row.category,
        "notes": row.notes,
        "frequencyType": row.frequency_type,
        "daysOfWeek": list(row.days_of_week),
        "timezone": row.timezone,
        "startDate": row.start_date.isoformat(),
        "endDate": row.end_date.isoformat() if row.end_date else None,
        "isActive": row.is_active,
        "scheduleRevision": row.schedule_revision,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def _snapshot(row) -> dict:
    "Full schedule snapshot carried by every Activity event"
    return {
        "activityId": str(row.id),
        "userId": str(row.user_id),
        "scheduleRevision": row.schedule_revision,
        "isActive": row.is_active,
        "frequencyType": row.frequency_type,
        "daysOfWeek": list(row.days_of_week),
        "timezone": row.timezone,
        "startDate": row.start_date.isoformat(),
        "endDate": row.end_date.isoformat() if row.end_date else None,
    }


def _today(tz_name: str) -> date:
    return datetime.now(load_zone(tz_name)).date()


def _emit(session: Session, event_type: str, row) -> None:
    insert_outbox(session, build_envelope(event_type, PRODUCER, _snapshot(row)))


def create_activity(session: Session, user_id: UUID, body: ActivityCreate):
    errors: list[dict] = []
    zone = load_zone(body.timezone)
    if zone is None:
        errors.append(field_error("timezone", "invalid_timezone", "Unkown timezone"))
    days, days_errors = normalize_days(body.frequencyType, body.daysOfWeek)
    errors += days_errors
    start = body.startDate
    if zone is not None:
        today = datetime.now(zone).date()
        start = start or today
        if start < today:
            errors.append(
                field_error(
                    "startDate",
                    "start_date_in_past",
                    "start date must not be before today",
                )
            )
    if body.endDate is not None and start is not None and body.endDate < start:
        errors.append(
            field_error(
                "endDate", "end_before_start", "endDate must be on or after startDate"
            )
        )
    if errors:
        raise validation_problem(errors)

    row = session.execute(
        sa.insert(activity)
        .values(
            user_id=user_id,
            title=body.title,
            category=body.category,
            notes=body.notes,
            frequency_type=body.frequencyType,
            days_of_week=days,
            timezone=body.timezone,
            start_date=start,
            end_date=body.endDate,
        )
        .returning(*activity.c)
    ).one()
    _emit(session, "ActivityCreated", row)
    return row


def get_activity(
    session: Session, user_id: UUID, activity_id: UUID, *, lock: bool = False
):
    q = sa.select(activity).where(
        activity.c.id == activity_id, activity.c.user_id == user_id
    )

    if lock:
        q.with_for_update()  # serializes concurrent PATCHes so schedule_revision never skips or repeats

    row = session.execute(q).first()
    if row is None:
        raise not_found("Activity")
    return row


def list_activities(
    session: Session,
    user_id: UUID,
    limit: int,
    cursor: str | None,
    include_inactive: bool,
) -> dict:
    q = sa.select(activity).where(activity.c.user_id == user_id)
    if not include_inactive:
        q = q.where(activity.c.is_active.is_(True))

    c = decode_cursor(cursor)
    if c:
        try:
            marker = (datetime.fromisoformat(c["c"]), UUID(c["i"]))
        except (KeyError, ValueError, TypeError):
            raise ProblemError("malformed-request", 400, "Invalid Cursor")
        q = q.where(
            sa.tuple_(activity.c.created_at, activity.c.id) < sa.tuple_(*marker)
        )
    rows = session.execute(
        q.order_by(activity.c.created_at.desc(), activity.c.id.desc()).limit(limit + 1)
    ).all()
    page, more = rows[:limit], len(rows) > limit
    nxt = (
        encode_cursor({"c": page[-1].created_at.isoformat(), "i": str(page[-1].id)})
        if more
        else None
    )
    return {"items": [to_api(r) for r in page], "nextCursor": nxt}


def update_activity(
    session: Session, user_id: UUID, activity_id: UUID, body: ActivityPatch
):
    current = get_activity(session, user_id, activity_id, lock=True)
    sent = body.model_fields_set
    values: dict = {}
    errors: list[dict] = []

    for api_name, column in (
        ("title", "title"),
        ("category", "category"),
        ("notes", "notes"),
    ):
        if api_name in sent:
            if getattr(body, api_name) is None:
                errors.append(
                    field_error(
                        api_name, "null_not_allowed", f"{api_name} cannot be null"
                    )
                )
            else:
                values[column] = getattr(body, api_name)
    if "isActive" in sent:
        if body.isActive is None:
            errors.append(
                field_error("isActive", "null_not_allowed", "isActive cannot be null")
            )
        else:
            values["is_active"] = body.isActive

    frequency = (
        body.frequencyType
        if "frequencyType" in sent and body.frequencyType
        else current.frequency_type
    )
    if "frequencyType" in sent and body.frequencyType is None:
        errors.append(
            field_error(
                "frequencyType", "null_not_allowed", "frequencyType cannot be null"
            )
        )
    tz = body.timezone if "timezone" in sent and body.timezone else current.timezone
    if "timezone" in sent and body.timezone is None:
        errors.append(
            field_error("timezone", "null_not_allowed", "timezone cannot be null")
        )
    if tz != current.timezone and load_zone(tz) is None:
        errors.append(
            field_error("timezone", "invalid_timezone", "Unknown IANA time zone")
        )

    if "daysOfWeek" in sent or "frequencyType" in sent:
        if "daysOfWeek" in sent:
            requested = body.daysOfWeek
        elif frequency == "WEEKLY" and current.frequency_type == "DAILY":
            requested = None  # changing DAILY -> WEEKLY must say which days
        elif frequency == "DAILY":
            requested = None  # DAILY always means every day
        else:
            requested = list(current.days_of_week)
        days, day_errors = normalize_days(frequency, requested)
        errors += day_errors
        values["days_of_week"] = days if days is not None else current.days_of_week
    if "frequencyType" in sent and body.frequencyType:
        values["frequency_type"] = body.frequencyType
    if "timezone" in sent and body.timezone:
        values["timezone"] = body.timezone

    start = body.startDate if "startDate" in sent else current.start_date
    if "startDate" in sent:
        if body.startDate is None:
            errors.append(
                field_error("startDate", "null_not_allowed", "startDate cannot be null")
            )
        elif body.startDate != current.start_date:
            if load_zone(tz) and body.startDate < _today(
                tz
            ):  # only a CHANGED start date is held to "not in the past"
                errors.append(
                    field_error(
                        "startDate",
                        "start_date_in_past",
                        "startDate must not be before today in the activity's time zone",
                    )
                )
            values["start_date"] = body.startDate
    end = body.endDate if "endDate" in sent else current.end_date
    if "endDate" in sent:
        values["end_date"] = body.endDate
    if start is not None and end is not None and end < start:
        errors.append(
            field_error(
                "endDate", "end_before_start", "endDate must be on or after startDate"
            )
        )
    if errors:
        raise validation_problem(errors)

    # Drop values that are equal, checking for scheduled changed or not
    values = {k: v for k, v in values.items() if getattr(current, k) != v}
    if not values:
        return current
    schedule_changed = any(k in values for k in SCHEDULE_FIELDS)
    if schedule_changed:
        values["scheduled_revision"] = current.schedule_revision + 1
    values["updated_at"] = datetime.now(UTC)

    row = session.execute(
        sa.update(activity)
        .where(activity.c.id == activity_id)
        .values(**values)
        .returning(*activity.c)
    ).one()

    if schedule_changed:
        _emit(
            session, "ActivityUpdated" if row.is_active else "ActivityDeactivated", row
        )
    return row


def deactivate_activity(session: Session, user_id: UUID, activity_id: UUID) -> None:
    current = get_activity(session, user_id, activity_id, lock=True)
    if not current.is_active:
        return
    row = session.execute(
        sa.update(activity)
        .where(activity.c.id == activity_id)
        .values(
            is_active=False,
            schedule_revision=current.schedule_revision + 1,
            updated_at=datetime.now(UTC),
        )
        .returning(*activity.c)
    ).one()

    _emit(session, "ActivityDeactivated",row)
