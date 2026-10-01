"""Small JSON log formatter that only emits explicitly selected metadata."""

import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    fields = (
        "request_id",
        "meeting_id",
        "job_id",
        "stage",
        "duration_ms",
        "provider",
        "attempt",
        "error_code",
        "status_code",
    )

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
        }
        for field in self.fields:
            value = getattr(record, field, None)
            if value is not None:
                event[field] = str(value) if field.endswith("_id") else value
        return json.dumps(event, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(lambda record: record.name.startswith("app."))
    root.handlers = [handler]
