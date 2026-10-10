"""Structured JSON logging with correlation ids and secret/content redaction."""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

from app.core.context import actor_var, correlation_id_var, tenant_var

_SENSITIVE = re.compile(r"(authorization|api[-_]?key|password|token|secret|content|text|enc_key|cookie)", re.I)


def _redact(v, depth=0):
    if depth > 4:
        return "…"
    if isinstance(v, dict):
        return {k: ("[REDACTED]" if _SENSITIVE.search(str(k)) else _redact(x, depth + 1)) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_redact(x, depth + 1) for x in list(v)[:20]]
    if isinstance(v, str) and len(v) > 300:
        return v[:300] + "…"
    return v


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            "correlationId": correlation_id_var.get(),
            "tenant": tenant_var.get(),
            "actor": actor_var.get(),
        }
        extra = getattr(record, "fields", None)
        if extra:
            payload.update(_redact(extra))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # we emit our own access log with correlation id


def get_logger(name: str) -> "FieldLogger":
    return FieldLogger(logging.getLogger(name))


class FieldLogger:
    def __init__(self, base: logging.Logger):
        self._b = base

    def _log(self, lvl, msg, **fields):
        self._b.log(lvl, msg, extra={"fields": fields} if fields else None)

    def debug(self, m, **f): self._log(logging.DEBUG, m, **f)
    def info(self, m, **f): self._log(logging.INFO, m, **f)
    def warning(self, m, **f): self._log(logging.WARNING, m, **f)
    def error(self, m, **f): self._log(logging.ERROR, m, **f)
    def exception(self, m, **f): self._b.exception(m, extra={"fields": f} if f else None)
