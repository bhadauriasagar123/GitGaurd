"""CQRS mediator: commands mutate (write model = PostgreSQL), queries read (read model = Redis-cached
analysis snapshots). Domain events fan out in-process and over Redis pub/sub."""
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Awaitable, Callable

from app.core.logging import get_logger

log = get_logger("cqrs")


class _Bus:
    kind = "message"

    def __init__(self):
        self._handlers: dict[type, Callable[[Any], Awaitable[Any]]] = {}

    def register(self, msg_type: type, handler: Callable[[Any], Awaitable[Any]]) -> None:
        if msg_type in self._handlers:
            raise RuntimeError(f"duplicate {self.kind} handler for {msg_type.__name__}")
        self._handlers[msg_type] = handler

    async def dispatch(self, msg: Any) -> Any:
        h = self._handlers.get(type(msg))
        if not h:
            raise RuntimeError(f"no {self.kind} handler for {type(msg).__name__}")
        return await h(msg)


class CommandBus(_Bus):
    kind = "command"


class QueryBus(_Bus):
    kind = "query"


class EventBus:
    CHANNEL = "regguard:events"

    def __init__(self, redis):
        self._redis = redis
        self._subs: dict[str, list[Callable[[dict], Awaitable[None]]]] = defaultdict(list)

    def subscribe(self, event: str, fn: Callable[[dict], Awaitable[None]]) -> None:
        self._subs[event].append(fn)

    async def publish(self, event: str, payload: dict) -> None:
        for fn in self._subs.get(event, []):
            try:
                await fn(payload)
            except Exception:
                log.exception("event handler failed", event=event)
        try:
            await self._redis.publish(self.CHANNEL, json.dumps({"event": event, **payload}, default=str))
        except Exception:
            log.warning("event publish failed", event=event)
