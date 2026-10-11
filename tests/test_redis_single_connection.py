"""Free-tier Redis: the app must never open more than REDIS_MAX_CONNECTIONS (default 1) connections per process.
Verified against a real RESP server (fakeredis TCP server) by counting connections accepted on the SERVER side."""
import asyncio
import threading

import pytest
from fakeredis import TcpFakeServer

from app.core.config import Settings, reset_settings_cache
from app.infra import redis_client


@pytest.fixture
def resp_server():
    srv = TcpFakeServer(("127.0.0.1", 0), server_type="redis")
    srv.daemon_threads = True      # handler threads must never block shutdown (clients keep their connection open)
    srv.block_on_close = False
    accepted = {"n": 0}
    orig = srv.process_request

    def counting(request, client_address):
        accepted["n"] += 1
        return orig(request, client_address)

    srv.process_request = counting
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"redis://127.0.0.1:{srv.server_address[1]}/0", accepted
    srv.shutdown()


@pytest.fixture
def fresh_client(monkeypatch):
    async def make(url, **env):
        monkeypatch.setenv("REDIS_URL", url)
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        reset_settings_cache()
        await redis_client.close_redis()
        return await redis_client.get_redis()
    yield make
    asyncio.get_event_loop_policy()  # keep linters quiet; teardown below
    redis_client._client = None
    reset_settings_cache()


def test_default_is_exactly_one_connection():
    s = Settings(_env_file=None)
    assert s.redis_max_connections == 1 and s.redis_pool_timeout_sec > 0
    with pytest.raises(ValueError):
        Settings(_env_file=None, redis_max_connections=0)


async def test_hundreds_of_concurrent_commands_share_one_connection(resp_server, fresh_client):
    url, accepted = resp_server
    r = await fresh_client(url)
    results = await asyncio.gather(*[r.incr("counter") for _ in range(200)], *[r.set(f"k{i}", i, ex=30) for i in range(100)])
    assert sorted(x for x in results[:200]) == list(range(1, 201))          # every command executed, in order, none lost
    assert accepted["n"] == 1                                                # ONE TCP connection ever accepted by the server
    pool = r.connection_pool
    assert len(pool._in_use_connections) + len(pool._available_connections) == 1


async def test_commands_queue_instead_of_opening_new_connections(resp_server, fresh_client):
    url, accepted = resp_server
    r = await fresh_client(url)
    order = []

    async def worker(i):
        await r.set(f"w{i}", i)
        order.append(i)
    await asyncio.gather(*[worker(i) for i in range(50)])
    assert len(order) == 50 and accepted["n"] == 1


async def test_exhausted_queue_fails_fast_not_by_opening_a_second_connection(resp_server, fresh_client):
    """With a tiny queue timeout and the only connection checked out, a second caller times out (-> 503 in the API)."""
    from redis.exceptions import ConnectionError as RedisConnectionError
    url, accepted = resp_server
    r = await fresh_client(url, REDIS_POOL_TIMEOUT_SEC="0.2")
    await r.ping()
    held = await r.connection_pool.get_connection()          # simulate a command in flight on the one connection
    try:
        with pytest.raises(RedisConnectionError):
            await r.ping()
    finally:
        await r.connection_pool.release(held)
    assert accepted["n"] == 1
    assert await r.ping() is True                              # healthy again once the connection is released


async def test_whole_api_runs_on_a_single_redis_connection(resp_server, monkeypatch):
    """Full app (rate limit, idempotency, locks, read-model cache, firewall sessions) under parallel load: still ONE connection."""
    import httpx
    from app.api import deps
    from app.infra.db import Database
    from tests.conftest import ANALYST, VIEWER
    url, accepted = resp_server
    monkeypatch.setenv("REDIS_URL", url)
    reset_settings_cache()
    deps.reset_key_ring()
    await Database.dispose()
    await redis_client.close_redis()
    from app.infra.orm import Base
    async with Database.instance().engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    from app.main import create_app
    app = create_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.post("/api/v1/sample/load", headers={**ANALYST, "Idempotency-Key": "single-conn-load-01"})).status_code == 200
            rs = await asyncio.gather(*[c.get("/api/v1/analysis/summary", headers=VIEWER) for _ in range(20)],
                                      *[c.post("/api/v1/firewall/scan", headers=ANALYST, json={"content": "Quarterly report due.", "sessionId": "s1"}) for _ in range(10)])
            assert all(r.status_code == 200 for r in rs), [r.status_code for r in rs]
            assert (await c.get("/readyz")).json()["checks"]["redis"] == "up"
    assert accepted["n"] == 1, f"{accepted['n']} connections were opened"
    redis_client._client = None
    reset_settings_cache()
