"""Request-scoped context (correlation id, tenant, actor) carried via contextvars."""
from __future__ import annotations

from contextvars import ContextVar

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
tenant_var: ContextVar[str] = ContextVar("tenant", default="-")
actor_var: ContextVar[str] = ContextVar("actor", default="-")


def correlation_id() -> str:
    return correlation_id_var.get()
