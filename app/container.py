"""Composition root / service container (dependency injection without a framework)."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings, get_settings
from app.cqrs.bus import CommandBus, EventBus, QueryBus
from app.firewall.engine import PromptInjectionFirewall
from app.firewall.session import SessionRiskTracker
from app.infra.db import Database
from app.infra.redis_client import get_redis
from app.llm.factory import build_provider


@dataclass
class Container:
    settings: Settings
    db: Database
    redis: object
    firewall: PromptInjectionFirewall
    commands: CommandBus
    queries: QueryBus
    events: EventBus
    llm: object


async def build_container() -> Container:
    settings = get_settings()
    db = Database.instance()
    await db.create_schema()
    redis = await get_redis()
    firewall = PromptInjectionFirewall(SessionRiskTracker(redis))
    events = EventBus(redis)
    c = Container(settings, db, redis, firewall, CommandBus(), QueryBus(), events, build_provider(settings))
    from app.cqrs import handlers  # registers handlers on the buses
    handlers.register(c)
    return c
