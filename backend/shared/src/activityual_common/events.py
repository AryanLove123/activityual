"""Event envelope construction and the outbox insert"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .logging import correlation_id_var


def build_envelope(event_type: str, producer: str, payload: dict[str, Any], *, occurred_at: datetime | None = None, event_id: uuid.UUID | None = None, correlation_id: str | None = None, version: int = 1) -> dict[str, Any]:
    return {
        "eventId": str(event_id or uuid.uuid4()),
        "eventType": event_type,
        "version": version,
        "occurredAt": (occurred_at or datetime.now(UTC)).isoformat(),
        "producer": producer,
        "correlationId": correlation_id or correlation_id_var.get() or str(uuid.uuid4()),
        "payload": payload,
    }


_INSERT = text(
    "INSERT INTO outbox_schema.outbox (event_id, event_type, event_version, producer, payload) "
    "VALUES (CAST(:event_id AS uuid), :event_type, :version, :producer, CAST(:payload AS jsonb))"
)

def insert_outbox(session: Session, envelope: dict[str, Any]) -> None:
    session.execute(_INSERT, {
        "event_id": envelope["eventId"], "event_type": envelope["eventType"],
        "version": envelope["version"], "producer": envelope["producer"],
        "payload": json.dumps(envelope),
    })