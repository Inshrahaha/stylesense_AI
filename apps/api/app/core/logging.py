"""
Structured JSON logging with request IDs and PII redaction.
"""

import json
import logging
import re
import sys
import uuid
from contextvars import ContextVar
from typing import Any

from app.config import get_settings

# Context variable for request ID propagation
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")

# PII patterns to redact from logs
PII_PATTERNS = [
    (re.compile(r'"email"\s*:\s*"[^"]*"'), '"email": "[REDACTED]"'),
    (re.compile(r'"password"\s*:\s*"[^"]*"'), '"password": "[REDACTED]"'),
    (re.compile(r'"password_hash"\s*:\s*"[^"]*"'), '"password_hash": "[REDACTED]"'),
    (re.compile(r'"token"\s*:\s*"[^"]*"'), '"token": "[REDACTED]"'),
    (re.compile(r'"refresh_token"\s*:\s*"[^"]*"'), '"refresh_token": "[REDACTED]"'),
    (re.compile(r'"access_token"\s*:\s*"[^"]*"'), '"access_token": "[REDACTED]"'),
    (re.compile(r'"authorization"\s*:\s*"[^"]*"', re.IGNORECASE), '"authorization": "[REDACTED]"'),
    (re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b'), "[REDACTED_EMAIL]"),
]


def redact_pii(message: str) -> str:
    """Remove PII from log messages."""
    for pattern, replacement in PII_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter with request ID and PII redaction."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_pii(record.getMessage()),
            "request_id": request_id_ctx.get(""),
        }

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = {
                "type": type(record.exc_info[1]).__name__,
                "message": redact_pii(str(record.exc_info[1])),
            }

        # Add extra fields
        for key in ("user_id", "action", "status_code", "method", "path", "duration_ms"):
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        return json.dumps(log_entry, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable log formatter for development."""

    def format(self, record: logging.LogRecord) -> str:
        req_id = request_id_ctx.get("")
        prefix = f"[{req_id[:8]}] " if req_id else ""
        msg = redact_pii(record.getMessage())
        return f"{self.formatTime(record)} {record.levelname:8s} {prefix}{record.name}: {msg}"


def setup_logging() -> None:
    """Configure application logging."""
    settings = get_settings()
    root = logging.getLogger()
    root.setLevel(settings.log_level)

    # Remove existing handlers
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    if settings.log_format == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(TextFormatter())

    root.addHandler(handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.database_echo else logging.WARNING
    )


def generate_request_id() -> str:
    """Generate a unique request ID."""
    return str(uuid.uuid4())


def get_logger(name: str) -> logging.Logger:
    """Get a named logger."""
    return logging.getLogger(f"stylesense.{name}")
