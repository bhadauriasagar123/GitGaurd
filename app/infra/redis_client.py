"""Redis client singleton + distributed lock + pub/sub event channel.

Redis roles in this system: idempotency records, rate-limit counters, firewall session risk
memory, CQRS read-model cache (analysis snapshots), per-tenant write locks, and domain-event
fan-out."""
from __future__ import annotations

import asyncio
import secrets
from contextlib import asynccontextmanager

from app.core.config import get_settings
from app.core.errors import Conflict
from app.core.logging import get_logger

log = get_logger("redis")

_client = None


async def get_redis():
    global _client
    if _client is None:
        url = get_settings().redis_url
        if url.startswith("fakeredis"):
            import fakeredis.aioredis as fr  # dev/test only

            log.warning("using fakeredis (in-process) - set REDIS_URL to a real Redis for production")
            _client = fr.FakeRedis(decode_responses=True)
        else:
            import redis.asyncio as aioredis

            s = get_settings()
            # Hard cap on connections (default 1, for free Redis tiers): a BLOCKING pool makes concurrent requests queue for the
            # single connection instead of opening new ones. If the queue wait exceeds the timeout the request fails with a 503.
            pool = aioredis.BlockingConnectionPool.from_url(url, max_connections=s.redis_max_connections, timeout=s.redis_pool_timeout_sec,
                                                            decode_responses=True, socket_timeout=5, socket_connect_timeout=5,
                                                            health_check_interval=30, retry_on_timeout=True)
            _client = aioredis.Redis(connection_pool=pool)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:
            pass
        _client = None


_RELEASE = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"


@asynccontextmanager
async def tenant_lock(redis, tenant: str, name: str, ttl: int = 90, wait: float = 40.0):
    """Token-owned distributed mutex (SET NX PX + compare-and-delete release)."""
    key, token = f"lock:{tenant}:{name}", secrets.token_hex(8)
    deadline = asyncio.get_event_loop().time() + wait
    while not await redis.set(key, token, nx=True, ex=ttl):
        if asyncio.get_event_loop().time() > deadline:
            raise Conflict(f"resource busy: {name}", headers={"Retry-After": "3"})
        await asyncio.sleep(0.05)
    try:
        yield
    finally:
        try:
            if await redis.get(key) == token:
                await redis.delete(key)
        except Exception:
            log.warning("lock release failed", key=key)
