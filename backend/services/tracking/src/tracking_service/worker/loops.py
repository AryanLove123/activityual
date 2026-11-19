"""The four worker loops, fetch -> call domain -> persist."""
import json
import logging
import random
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.config import Config
from sqlalchemy.orm import Session, sessionmaker

from .. import repo
from ..domain.generation import plan_generation
from ..domain.revisions import effective_from_for, invalid_pending_dates
from ..settings import WorkerSettings

log = logging.getLogger("activityual.worker")
KNOWN_EVENTS = {"ActivityCreated", "ActivityUpdated", "ActivityDeactivated"}

class Loop:
    """Runs step() forever. step() returns True when there is more work waiting (run again at once)."""

    def __init__(self, name: str, period: float, step: Callable[[], bool], wake: threading.Event | None = None) -> None:
        self.name, self.period, self.step, self.wake = name, period, step, wake

    def _sleep(self, stop: threading.Event, seconds: float) -> None:
        """Sleep in short slices so Ctrl+C (stop) or a wake-up is noticed within half a second."""
        remaining = seconds
        while remaining > 0 and not stop.is_set():
            part = min(remaining, 0.5)
            if self.wake is not None:
                if self.wake.wait(part):
                    self.wake.clear()
                    return
            else:
                stop.wait(part)
            remaining -= part

    def run(self, stop: threading.Event) -> None:
        failures = 0
        while not stop.is_set():
            try:
                more = self.step()
                failures = 0
                delay = 0.0 if more else self.period
            except Exception as exc:
                failures += 1
                log.error("loop iteration failed: %s: %s", type(exc).__name__, exc, extra={"loop": self.name})
                delay = min(60.0, 2.0 ** min(failures, 6)) * (0.5 + random.random() / 2)   # backoff + jitter
            if delay:
                self._sleep(stop, delay)


def aws_client(service: str, s: WorkerSettings):
    return boto3.client(service, region_name=s.aws_region, endpoint_url=s.aws_endpoint_url,
                        config=Config(connect_timeout=3, read_timeout=25 if service == "sqs" else 10,
                                      retries={"max_attempts": 3, "mode": "standard"}))


# -----------------outbox relay----------------------#

class OutboxRelay:
    def __init__(self, factory: sessionmaker[Session], s: WorkerSettings, events=None) -> None:
        self.factory, self.s = factory, s
        self.events = events or aws_client("events", s)
        self._last_cleanup = 0.0

    def step(self) -> bool:
        import time
        if time.time() - self._last_cleanup > self.s.relay_cleanup_interval_seconds:
            with self.factory.begin() as session:               # only PUBLISHED rows are ever deleted
                deleted = repo.cleanup_outbox(session, self.s.relay_retention_days)
            self._last_cleanup = time.time()
            log.info("outbox cleanup", extra={"deleted": deleted})
        with self.factory.begin() as session:                    # 1. short transaction: claim with a lease, COMMIT
            rows = repo.claim_outbox(session, self.s.relay_batch_size, self.s.relay_lease_seconds)
        for i in range(0, len(rows), 10):                       # 2. network calls with NO transaction open
            self._publish(rows[i:i + 10])
        return len(rows) >= self.s.relay_batch_size

    def _publish(self, chunk: list[dict[str, Any]]) -> None:
        entries = [{"EventBusName": self.s.event_bus_name,
                    "Source": f"activityual.{r['payload']['producer']}",
                    "DetailType": r["event_type"],
                    "Detail": json.dumps(r["payload"])} for r in chunk]
        ok: list[int] = []
        failed: list[tuple[int, str]] = []
        try:
            resp = self.events.put_events(Entries=entries)
            for row, entry in zip(chunk, resp["Entries"], strict=True):
                if "ErrorCode" in entry:
                    failed.append((row["id"], f"{entry['ErrorCode']}: {entry.get('ErrorMessage', '')}"))
                else:
                    ok.append(row["id"])
        except Exception as exc:   # noqa: BLE001 - network/throttling: the whole chunk is retried later
            failed = [(r["id"], f"{type(exc).__name__}: {exc}") for r in chunk]
        with self.factory.begin() as session:                    # 3. record the outcome
            if ok:
                repo.mark_published(session, ok)
            for row_id, err in failed:
                repo.mark_failed(session, [row_id], err, self.s.relay_max_attempts)
        if failed:
            log.warning("outbox publish failures", extra={"failed": len(failed), "published": len(ok)})


# ------------------------overdue loop---------------------#

class OverdueProcessor:
    def __init__(self, factory: sessionmaker[Session], s: WorkerSettings) -> None:
        self.factory, self.s = factory, s

    def step(self) -> bool:
        with self.factory.begin() as session:
            n = repo.mark_overdue(session, self.s.overdue_batch_size)
        if n:
            log.info("occurrences marked missed", extra={"count": n})
        return n >= self.s.overdue_batch_size


# -------------------generator loop--------------------#

class OccurrenceGenerator:
    def __init__(self, factory: sessionmaker[Session], s: WorkerSettings) -> None:
        self.factory, self.s = factory, s

    def step(self) -> bool:
        more = False
        with self.factory.begin() as session:           # one transaction per bounded batch of schedules
            picked = repo.pick_schedules(session, self.s.generation_horizon_days, self.s.generation_batch_schedules)
            for sched in picked:
                revisions = repo.load_revisions(session, sched.activity_id)
                plan = plan_generation(today=repo.local_today(session, sched.timezone),
                                       generated_through=sched.generated_through, revisions=revisions,
                                       horizon_days=self.s.generation_horizon_days,
                                       batch_days=self.s.generation_batch_days,
                                       max_lookback_days=self.s.generation_max_lookback_days)
                if plan.gap_days:     # never silent: history older than the look-back cap is reported
                    log.error("generation gap", extra={"activityId": str(sched.activity_id), "days": plan.gap_days})
                for o in plan.occurrences:
                    repo.insert_occurrence(session, sched.activity_id, sched.user_id, o.scheduled_date, o.timezone,
                                           o.window.start, o.window.end)
                if plan.through is not None:
                    repo.advance_watermark(session, sched.activity_id, plan.through)   # same transaction
                more = more or plan.more
            full_batch = len(picked) >= self.s.generation_batch_schedules
        return more or full_batch


# ---------------activity-event consumer----------------#

class PoisonMessage(Exception):
    pass


def parse_activity_event(body: str) -> dict[str, Any]:
    """EventBridge -> SQS delivers a wrapper; the business envelope is body['detail'] (event-driven-design.md 2)."""
    try:
        doc = json.loads(body)
    except ValueError as exc:
        raise PoisonMessage("body is not JSON") from exc
    env = doc.get("detail", doc) if isinstance(doc, dict) else None
    if not isinstance(env, dict):
        raise PoisonMessage("no envelope")
    if env.get("version") != 1 or env.get("eventType") not in KNOWN_EVENTS:
        raise PoisonMessage(f"unsupported event {env.get('eventType')!r} v{env.get('version')!r}")
    p = env.get("payload")
    needed = {"activityId", "userId", "scheduleRevision", "isActive", "frequencyType", "daysOfWeek", "timezone",
              "startDate"}
    if not isinstance(p, dict) or not needed <= p.keys() or not env.get("eventId") or not env.get("occurredAt"):
        raise PoisonMessage("missing required fields")
    return env


class ActivityEventConsumer:
    def __init__(self, factory: sessionmaker[Session], s: WorkerSettings, wake: threading.Event,
                 sqs=None) -> None:
        self.factory, self.s, self.wake = factory, s, wake
        self.sqs = sqs or aws_client("sqs", s)

    def step(self) -> bool:
        resp = self.sqs.receive_message(QueueUrl=self.s.sqs_tracking_activity_queue_url,
                                        MaxNumberOfMessages=self.s.consumer_max_messages,
                                        WaitTimeSeconds=self.s.consumer_wait_seconds)
        messages = resp.get("Messages", [])
        failed = 0
        for m in messages:
            try:
                self.apply(parse_activity_event(m["Body"]))
            except PoisonMessage as exc:
                failed += 1          # never deleted: it lands in the DLQ after maxReceiveCount (alarm)
                log.error("poison message", extra={"reason": str(exc), "messageId": m.get("MessageId")})
                continue
            self.sqs.delete_message(QueueUrl=self.s.sqs_tracking_activity_queue_url, ReceiptHandle=m["ReceiptHandle"])
        return False

    def apply(self, env: dict[str, Any]) -> None:
        p = env["payload"]
        occurred = datetime.fromisoformat(env["occurredAt"]).astimezone(UTC)
        eff = effective_from_for(occurred, p["timezone"], datetime.fromisoformat(p["startDate"]).date())
        with self.factory.begin() as session:
            current = repo.apply_revision(session, p, eff, env["eventId"])
            if not p["isActive"] and p["scheduleRevision"] == current:
                repo.delete_all_pending(session, p["activityId"])           # deactivation: ALL pending, incl. open
            else:
                revisions = repo.load_revisions(session, p["activityId"])
                invalid = invalid_pending_dates(repo.future_pending(session, p["activityId"]), revisions)
                repo.delete_invalid_pending(session, p["activityId"], invalid)
                if p["isActive"]:
                    from datetime import timedelta
                    repo.rewind_watermark(session, p["activityId"], eff - timedelta(days=1))
        self.wake.set()   # tell the generator to run now