import json
import logging
import os
import time
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logger = logging.getLogger("bartenders")

# Google Cloud Logging severity strings
_GCP_SEVERITY = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}

# LogRecord attributes we don't want to serialize as "extra" fields
_RESERVED_ATTRS = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "message",
    "module",
    "msecs",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Structured JSON formatter compatible with Google Cloud Logging.

    Fields like ``severity`` and ``message`` are top-level so Cloud Logging
    parses them automatically into LogEntry fields. Any ``extra={...}`` passed
    to a log call is merged into the JSON payload (canonical log line pattern).
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "severity": _GCP_SEVERITY.get(record.levelname, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # Merge any extra fields (from logger.info("msg", extra={...}))
        for key, value in record.__dict__.items():
            if key in _RESERVED_ATTRS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        return json.dumps(payload, default=str)


def setup_logging() -> None:
    """Install the JSON formatter on the root logger and uvicorn loggers.

    Called once at application startup. Safe to call multiple times.
    """
    formatter = JsonFormatter()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL)

    # Force uvicorn's own loggers to propagate through the root handler
    # (uvicorn configures them with their own handlers by default).
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    logger.setLevel(LOG_LEVEL)


class CanonicalLogMiddleware(BaseHTTPMiddleware):
    """Emit one structured "wide" log line per HTTP request.

    Each request produces a single log entry with request metadata
    (method, path, status, latency, client) plus any fields added via
    ``request.state.log_fields[key] = value`` from inside the handler.
    """

    async def dispatch(self, request, call_next):
        start = time.perf_counter()
        request.state.log_fields = {}
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            fields = {
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status": status_code,
                "latency_ms": latency_ms,
                "client_ip": request.client.host if request.client else None,
                "user_agent": request.headers.get("user-agent"),
                **getattr(request.state, "log_fields", {}),
            }
            if status_code >= 500:
                level = logging.ERROR
            elif status_code >= 400:
                level = logging.WARNING
            else:
                level = logging.INFO
            logger.log(level, "http_request", extra=fields)
