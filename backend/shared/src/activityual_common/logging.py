"""Structured JSON logging with a correlation id for the microservices."""
import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

# Python mechanism that safely stores data tied to the current execution thread 
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default = None)

# acts as a filter whitelist to seperate standard Python logging from custom structured logs 
_RESERVED = set(logging.LogRecord("",0,"",0,"",(),None).__dict__) | {"message","asctime"}

# Custom JSON Formatter that outputs only the custom context fields alongside the standard log data 
class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        cid = correlation_id_var.get()
        if cid:
            doc["correlationId"] = cid
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                doc[key] = value
        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)

        return json.dumps(doc, default=str)

def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").disabled = True
