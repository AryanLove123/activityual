"""All SQL used by the Tracking API and worker."""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from .domain.revisions import PendingOccurrence, Revision

# --------------- API-------------------------#

_TRANSITION = {
    "COMPLETED": text("""
WITH done AS (
  UPDATE tracking_schema.occurrence
     SET state = 'COMPLETED', completed_at = now(), resolved_at = now()
   WHERE id = CAST(:oid AS uuid) AND user_id = CAST(:uid AS uuid)
     AND state = 'PENDING' AND due_start_at <= now() AND now() < due_end_at
  RETURNING id, activity_id, user_id, scheduled_date, timezone, completed_at
), ev AS (SELECT d.*, gen_random_uuid() AS event_id FROM done d)
INSERT INTO outbox_schema.outbox (event_id, event_type, event_version, producer, payload)
SELECT event_id, 'ActivityCompleted', 1, 'tracking-service',
       jsonb_build_object(
         'eventId', event_id, 'eventType', 'ActivityCompleted', 'version', 1,
         'occurredAt', completed_at, 'producer', 'tracking-service',
         'correlationId', CAST(:cid AS uuid),
         'payload', jsonb_build_object(
            'userId', user_id, 'activityId', activity_id, 'occurrenceId', id,
            'scheduledDate', scheduled_date, 'timezone', timezone, 'completedAt', completed_at))
  FROM ev
RETURNING id"""),
    "SKIPPED": text("""
WITH done AS (
  UPDATE tracking_schema.occurrence
     SET state = 'SKIPPED', resolved_at = now()
   WHERE id = CAST(:oid AS uuid) AND user_id = CAST(:uid AS uuid)
     AND state = 'PENDING' AND due_start_at <= now() AND now() < due_end_at
  RETURNING id, activity_id, user_id, scheduled_date, timezone, resolved_at
), ev AS (SELECT d.*, gen_random_uuid() AS event_id FROM done d)
INSERT INTO outbox_schema.outbox (event_id, event_type, event_version, producer, payload)
SELECT event_id, 'ActivitySkipped', 1, 'tracking-service',
       jsonb_build_object(
         'eventId', event_id, 'eventType', 'ActivitySkipped', 'version', 1,
         'occurredAt', resolved_at, 'producer', 'tracking-service',
         'correlationId', CAST(:cid AS uuid),
         'payload', jsonb_build_object(
            'userId', user_id, 'activityId', activity_id, 'occurrenceId', id,
            'scheduledDate', scheduled_date, 'timezone', timezone, 'skippedAt', resolved_at))
  FROM ev
RETURNING id"""),
}


def transition(
    session: Session,
    target: str,
    occurrence_id: UUID,
    user_id: UUID,
    correlation_id: str,
) -> int:
    """Atomically move PENDING -> target AND write the outbox row. Returns rows written (0 = no transition)."""
    return len(
        session.execute(
            _TRANSITION[target],
            {"oid": str(occurrence_id), "uid": str(user_id), "cid": correlation_id},
        ).all()
    )


@dataclass(frozen=True)
class OccurrenceRow:
    id: UUID
    activity_id: UUID
    scheduled_date: date
    timezone: str
    due_start_at: datetime
    due_end_at: datetime
    state: str
    completed_at: datetime | None
    resolved_at: datetime | None


_COLS = "id, activity_id, scheduled_date, timezone, due_start_at, due_end_at, state, completed_at, resolved_at"


def get_occurrence(
    session: Session, occurrence_id: UUID, user_id: UUID
) -> OccurrenceRow | None:
    row = session.execute(
        text(
            f"SELECT {_COLS} FROM tracking_schema.occurrence "
            "WHERE id = :oid AND user_id = :uid"
        ),
        {"oid": occurrence_id, "uid": user_id},
    ).first()
    return OccurrenceRow(*row) if row else None


def db_now(session: Session) -> datetime:
    return session.execute(text("SELECT now()")).scalar_one()


def db_today(session: Session) -> date:
    return session.execute(text("SELECT (now() AT TIME ZONE 'UTC')::date")).scalar_one()


def list_occurrences(
    session: Session,
    user_id: UUID,
    start: date,
    end: date,
    activity_id: UUID | None,
    states: list[str] | None,
    limit: int,
    after: tuple[date, UUID] | None,
) -> list[OccurrenceRow]:
    sql = f"SELECT {_COLS} FROM tracking_schema.occurrence WHERE user_id = :uid AND scheduled_date BETWEEN :a AND :b"
    params: dict[str, Any] = {"uid": user_id, "a": start, "b": end, "lim": limit + 1}
    if activity_id:
        sql += " AND activity_id = :act"
        params["act"] = activity_id
    if states:
        sql += " AND state = ANY(:states)"
        params["states"] = states
    if after:
        sql += " AND (scheduled_date, id) < (:cd, :cid)"
        params["cd"], params["cid"] = after
    sql += " ORDER BY scheduled_date DESC, id DESC LIMIT :lim"
    return [OccurrenceRow(*r) for r in session.execute(text(sql), params).all()]


# -----------------------Worker---------------------------#

_OVERDUE = text("""
WITH due AS (
  SELECT id FROM tracking_schema.occurrence
   WHERE state = 'PENDING' AND due_end_at <= now()
   ORDER BY due_end_at, id
   LIMIT :batch
   FOR UPDATE SKIP LOCKED
), upd AS (
  UPDATE tracking_schema.occurrence o
     SET state = 'MISSED', resolved_at = now()
    FROM due
   WHERE o.id = due.id
  RETURNING o.id, o.activity_id, o.user_id, o.scheduled_date, o.timezone, o.due_end_at, o.resolved_at
), ev AS (SELECT u.*, gen_random_uuid() AS event_id, gen_random_uuid() AS correlation_id FROM upd u)
INSERT INTO outbox_schema.outbox (event_id, event_type, event_version, producer, payload)
SELECT event_id, 'ActivityMissed', 1, 'tracking-service',
       jsonb_build_object(
         'eventId', event_id, 'eventType', 'ActivityMissed', 'version', 1,
         'occurredAt', resolved_at, 'producer', 'tracking-service', 'correlationId', correlation_id,
         'payload', jsonb_build_object(
            'userId', user_id, 'activityId', activity_id, 'occurrenceId', id,
            'scheduledDate', scheduled_date, 'timezone', timezone, 'dueEndAt', due_end_at))
  FROM ev
RETURNING id""")


def mark_overdue(session: Session, batch: int) -> int:
    return len(session.execute(_OVERDUE, {"batch": batch}).all())


@dataclass(frozen=True)
class ScheduleRow:
    activity_id: UUID
    user_id: UUID
    current_revision: int
    timezone: str
    generated_through: date | None


def pick_schedules(
    session: Session, horizon_days: int, batch: int
) -> list[ScheduleRow]:
    rows = session.execute(
        text("""
SELECT activity_id, user_id, current_revision, timezone, generated_through
  FROM tracking_schema.activity_schedule
 WHERE generated_through IS NULL
    OR generated_through < ((now() AT TIME ZONE timezone)::date + :h)
 ORDER BY generated_through NULLS FIRST, activity_id
 LIMIT :b
 FOR UPDATE SKIP LOCKED"""),
        {"h": horizon_days, "b": batch},
    ).all()
    return [ScheduleRow(*r) for r in rows]


def local_today(session: Session, timezone: str) -> date:
    return session.execute(
        text("SELECT (now() AT TIME ZONE :tz)::date"), {"tz": timezone}
    ).scalar_one()


def load_revisions(session: Session, activity_id: UUID) -> list[Revision]:
    rows = session.execute(
        text("""
SELECT schedule_revision, frequency_type, days_of_week, timezone, start_date, end_date, is_active, effective_from
  FROM tracking_schema.activity_schedule_revision WHERE activity_id = :a ORDER BY schedule_revision"""),
        {"a": activity_id},
    ).all()
    return [
        Revision(r[0], r[1], tuple(int(d) for d in r[2]), r[3], r[4], r[5], r[6], r[7])
        for r in rows
    ]


def insert_occurrence(
    session: Session,
    activity_id: UUID,
    user_id: UUID,
    d: date,
    tz: str,
    start: datetime,
    end: datetime,
) -> bool:
    return (
        session.execute(
            text("""
INSERT INTO tracking_schema.occurrence (activity_id, user_id, scheduled_date, timezone, due_start_at, due_end_at)
VALUES (:a, :u, :d, :tz, :s, :e)
ON CONFLICT (activity_id, scheduled_date) DO NOTHING RETURNING id"""),
            {"a": activity_id, "u": user_id, "d": d, "tz": tz, "s": start, "e": end},
        ).first()
        is not None
    )


def advance_watermark(session: Session, activity_id: UUID, through: date) -> None:
    session.execute(
        text("""
UPDATE tracking_schema.activity_schedule SET generated_through = :t, updated_at = now()
 WHERE activity_id = :a AND (generated_through IS NULL OR generated_through < :t)"""),
        {"a": activity_id, "t": through},
    )


def rewind_watermark(session: Session, activity_id: UUID, before: date) -> None:
    session.execute(
        text("""
UPDATE tracking_schema.activity_schedule SET generated_through = LEAST(generated_through, :b), updated_at = now()
 WHERE activity_id = :a AND generated_through IS NOT NULL"""),
        {"a": activity_id, "b": before},
    )


def apply_revision(
    session: Session, p: dict[str, Any], effective_from: date, source_event_id: str
) -> int:
    """Idempotent, order-tolerant projection update. Returns the current revision after applying."""
    params = {
        "a": p["activityId"],
        "u": p["userId"],
        "r": p["scheduleRevision"],
        "f": p["frequencyType"],
        "dow": list(p["daysOfWeek"]),
        "tz": p["timezone"],
        "sd": date.fromisoformat(p["startDate"]),
        "ed": date.fromisoformat(p["endDate"]) if p.get("endDate") else None,
        "act": p["isActive"],
        "eff": effective_from,
        "ev": source_event_id,
    }
    session.execute(
        text("""
INSERT INTO tracking_schema.activity_schedule (activity_id, user_id, current_revision, timezone)
VALUES (CAST(:a AS uuid), CAST(:u AS uuid), :r, :tz) ON CONFLICT (activity_id) DO NOTHING"""),
        params,
    )
    session.execute(
        text("""
INSERT INTO tracking_schema.activity_schedule_revision
  (activity_id, schedule_revision, frequency_type, days_of_week, timezone, start_date, end_date,
   is_active, effective_from, source_event_id)
VALUES (CAST(:a AS uuid), :r, :f, CAST(:dow AS smallint[]), :tz, :sd, :ed, :act, :eff, CAST(:ev AS uuid))
ON CONFLICT (activity_id, schedule_revision) DO NOTHING"""),
        params,
    )
    session.execute(
        text("""
UPDATE tracking_schema.activity_schedule SET current_revision = :r, timezone = :tz, updated_at = now()
 WHERE activity_id = CAST(:a AS uuid) AND current_revision < :r"""),
        params,
    )
    return session.execute(
        text(
            "SELECT current_revision FROM tracking_schema.activity_schedule "
            "WHERE activity_id = CAST(:a AS uuid)"
        ),
        params,
    ).scalar_one()


def delete_all_pending(session: Session, activity_id: UUID | str) -> int:
    return len(
        session.execute(
            text("""
DELETE FROM tracking_schema.occurrence WHERE activity_id = CAST(:a AS uuid) AND state = 'PENDING' RETURNING id"""),
            {"a": str(activity_id)},
        ).all()
    )


def future_pending(
    session: Session, activity_id: UUID | str
) -> list[PendingOccurrence]:
    rows = session.execute(
        text("""
SELECT scheduled_date, timezone, due_start_at, due_end_at FROM tracking_schema.occurrence
 WHERE activity_id = CAST(:a AS uuid) AND state = 'PENDING' AND due_start_at > now()"""),
        {"a": str(activity_id)},
    ).all()
    return [PendingOccurrence(*r) for r in rows]


def delete_invalid_pending(
    session: Session, activity_id: UUID | str, dates: list[date]
) -> int:
    if not dates:
        return 0
    return len(
        session.execute(
            text("""
DELETE FROM tracking_schema.occurrence
 WHERE activity_id = CAST(:a AS uuid) AND state = 'PENDING' AND due_start_at > now()
   AND scheduled_date = ANY(:d) RETURNING id"""),
            {"a": str(activity_id), "d": dates},
        ).all()
    )


# ---------------Outbox-------------------------#

def claim_outbox(
    session: Session, batch: int, lease_seconds: int
) -> list[dict[str, Any]]:
    rows = session.execute(
        text("""
WITH c AS (
  SELECT id FROM outbox_schema.outbox
   WHERE status = 'PENDING' AND next_attempt_at <= now() AND (locked_until IS NULL OR locked_until < now())
   ORDER BY id LIMIT :b FOR UPDATE SKIP LOCKED
)
UPDATE outbox_schema.outbox o
   SET attempts = o.attempts + 1, locked_until = now() + make_interval(secs => :lease)
  FROM c WHERE o.id = c.id
RETURNING o.id, o.event_id, o.event_type, o.attempts, o.payload"""),
        {"b": batch, "lease": lease_seconds},
    ).all()
    return [
        {
            "id": r[0],
            "event_id": str(r[1]),
            "event_type": r[2],
            "attempts": r[3],
            "payload": r[4],
        }
        for r in rows
    ]


def mark_published(session: Session, ids: list[int]) -> None:
    session.execute(
        text("""
UPDATE outbox_schema.outbox SET status = 'PUBLISHED', published_at = now(), locked_until = NULL, last_error = NULL
 WHERE id = ANY(:ids) AND status = 'PENDING'"""),
        {"ids": ids},
    )


def mark_failed(
    session: Session, ids: list[int], error: str, max_attempts: int
) -> None:
    session.execute(
        text("""
UPDATE outbox_schema.outbox
   SET status = CASE WHEN attempts >= :m THEN 'DEAD' ELSE 'PENDING' END,
       next_attempt_at = now() + LEAST(power(2, attempts), 300) * interval '1 second',
       locked_until = NULL, last_error = left(:err, 1000)
 WHERE id = ANY(:ids) AND status = 'PENDING'"""),
        {"ids": ids, "err": error, "m": max_attempts},
    )


def cleanup_outbox(session: Session, retention_days: int) -> int:
    return len(
        session.execute(
            text("""
DELETE FROM outbox_schema.outbox
 WHERE status = 'PUBLISHED' AND published_at < now() - make_interval(days => :d)
RETURNING id"""),
            {"d": retention_days},
        ).all()
    )


# ---------------Metrics-------------------------#


def outbox_stats(session: Session) -> tuple[float, int]:
    row = session.execute(
        text("""
SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(created_at) FILTER (WHERE status = 'PENDING')), 0),
       count(*) FILTER (WHERE status = 'DEAD') FROM outbox_schema.outbox""")
    ).one()
    return float(row[0]), int(row[1])


def tracking_stats(session: Session) -> tuple[float, int]:
    row = session.execute(
        text("""
SELECT COALESCE((SELECT EXTRACT(EPOCH FROM now() - min(due_end_at)) FROM tracking_schema.occurrence
                  WHERE state = 'PENDING' AND due_end_at <= now()), 0),
       (SELECT count(*) FROM tracking_schema.activity_schedule
         WHERE generated_through IS NULL OR generated_through < ((now() AT TIME ZONE timezone)::date + 6))""")
    ).one()
    return float(row[0]), int(row[1])
