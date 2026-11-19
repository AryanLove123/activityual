from datetime import date, timedelta
from typing import Annotated
from uuid import UUID

from activityual_common.logging import correlation_id_var
from activityual_common.pagination import decode_cursor, encode_cursor
from activityual_common.problems import ProblemError, not_found
from activityual_common.security import CurrentUser
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import repo

STATES = {"PENDING", "COMPLETED", "SKIPPED", "MISSED"}
MAX_SPAN_DAYS = 60


def to_api(o: repo.OccurrenceRow) -> dict:
    return {
        "id": str(o.id),
        "activityId": str(o.activity_id),
        "scheduledDate": o.scheduled_date.isoformat(),
        "timezone": o.timezone,
        "dueStartAt": o.due_start_at.isoformat(),
        "dueEndAt": o.due_end_at.isoformat(),
        "state": o.state,
        "completedAt": o.completed_at.isoformat() if o.completed_at else None,
        "resolvedAt": o.resolved_at.isoformat() if o.resolved_at else None,
    }


def _validation(field: str, code: str, message: str) -> ProblemError:
    return ProblemError(
        "validation-error",
        422,
        "Request validation failed",
        errors=[{"field": field, "code": code, "message": message}],
    )


def build_router(get_session, current_user) -> APIRouter:
    router = APIRouter(prefix="/api/occurrences", tags=["occurrences"])

    @router.get("")
    def list_(
        session: Annotated[Session, Depends(get_session)],
        user: Annotated[CurrentUser, Depends(current_user)],
        from_: Annotated[date | None, Query(alias="from")] = None,
        to: date | None = None,
        activityId: UUID | None = None,
        state: Annotated[list[str] | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        cursor: str | None = None,
    ) -> dict:
        today = repo.db_today(session)
        start, end = from_ or today - timedelta(days=6), to or today + timedelta(days=6)
        if end < start:
            raise _validation("to", "before_from", "'to' must not be before 'from'")
        if (end - start).days + 1 > MAX_SPAN_DAYS:
            raise _validation(
                "to",
                "span_too_large",
                f"The range may span at most {MAX_SPAN_DAYS} days",
            )
        states = [s.upper() for s in state] if state else None
        if states and not set(states) <= STATES:
            raise _validation(
                "state", "invalid_state", f"state must be one of {sorted(STATES)}"
            )
        after = None
        if (c := decode_cursor(cursor)) is not None:
            try:
                after = (date.fromisoformat(c["d"]), UUID(c["id"]))
            except (KeyError, ValueError):
                raise ProblemError("malformed-request", 400, "Invalid cursor") from None
        rows = repo.list_occurrences(
            session, user.id, start, end, activityId, states, limit, after
        )
        page, more = rows[:limit], len(rows) > limit
        nxt = (
            encode_cursor(
                {"d": page[-1].scheduled_date.isoformat(), "id": str(page[-1].id)}
            )
            if more
            else None
        )
        return {"items": [to_api(o) for o in page], "nextCursor": nxt}

    @router.get("/{occurrence_id}")
    def get_one(
        occurrence_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> dict:
        row = repo.get_occurrence(session, occurrence_id, user.id)
        if row is None:
            raise not_found("Occurrence")
        return to_api(row)

    def resolve(
        occurrence_id: UUID, target: str, session: Session, user: CurrentUser
    ) -> dict:
        written = repo.transition(
            session, target, occurrence_id, user.id, correlation_id_var.get() or ""
        )
        row = repo.get_occurrence(session, occurrence_id, user.id)
        if row is None:
            raise not_found("Occurrence")
        if written or row.state == target:
            return to_api(row)
        if row.state != "PENDING":
            raise ProblemError(
                "occurrence-state-conflict",
                409,
                "The occurrence was already resolved differently",
                f"Current state is {row.state}.",
            )
        if repo.db_now(session) < row.due_start_at:
            raise ProblemError(
                "occurrence-window-not-open",
                409,
                "The due window has not opened yet",
                f"The window opens at {row.due_start_at.isoformat()}.",
            )
        raise ProblemError(
            "occurrence-window-closed",
            409,
            "The due window for this occurrence has ended",
            f"The window closed at {row.due_end_at.isoformat()}.",
        )

    @router.post("/{occurrence_id}/complete")
    def complete(
        occurrence_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> dict:
        return resolve(occurrence_id, "COMPLETED", session, user)

    @router.post("/{occurrence_id}/skip")
    def skip(
        occurrence_id: UUID,
        session: Annotated[Session, Depends(get_session)],
        user: Annotated[CurrentUser, Depends(current_user)],
    ) -> dict:
        return resolve(occurrence_id, "SKIPPED", session, user)

    return router
