import base64
import json
from typing import Any

from activityual_common.problems import ProblemError


def encode_cursor(values: dict[str, Any]) -> str:
    return base64.urlsafe_b64encode(json.dumps(values, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor: 
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise TypeError
        return data
    except TypeError:
        raise ProblemError("malformed-request", 400, "Invalid Cursor")