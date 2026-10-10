"""FastAPI dependencies: authentication (API key), RBAC, rate limiting, idempotency."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse

from app.core import crypto
from app.core.config import get_settings
from app.core.context import actor_var, tenant_var
from app.core.errors import Conflict, Forbidden, RateLimited, Unauthenticated, Unprocessable, ValidationFailed

ROLE_RANK = {"viewer": 1, "analyst": 2, "admin": 3}
_KEY_RING: list[dict] | None = None


@dataclass(frozen=True)
class Principal:
    tenant: str
    role: str
    label: str


def _ring() -> list[dict]:
    global _KEY_RING
    if _KEY_RING is None:
        _KEY_RING = get_settings().key_ring()
    return _KEY_RING


def reset_key_ring() -> None:
    global _KEY_RING
    _KEY_RING = None


async def authenticate(request: Request) -> Principal:
    auth = request.headers.get("authorization", "")
    key = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-api-key", "").strip()
    if not key or len(key) > 256:
        raise Unauthenticated("Missing API key (Authorization: Bearer <key> or X-API-Key)", headers={"WWW-Authenticate": "Bearer"})
    h = hashlib.sha256(key.encode()).hexdigest()
    found = None
    for entry in _ring():  # constant-time over the whole ring - no early exit side channel
        if crypto.safe_equal(entry["hash"], h):
            found = entry
    if not found:
        raise Unauthenticated("Invalid API key", headers={"WWW-Authenticate": "Bearer"})
    p = Principal(found["tenant"], found["role"], f"{found['role']}@{found['tenant']}:{h[:6]}")
    tenant_var.set(p.tenant)
    actor_var.set(p.label)
    request.state.principal = p
    return p


def require(role: str) -> Callable[..., Awaitable[Principal]]:
    async def dep(p: Principal = Depends(authenticate)) -> Principal:
        if ROLE_RANK[p.role] < ROLE_RANK[role]:
            raise Forbidden(f"Requires role '{role}' (you are '{p.role}')")
        return p
    return dep


def rate_limit(kind: str = "general"):
    async def dep(request: Request, response: Response, p: Principal = Depends(authenticate)) -> None:
        s = get_settings()
        limit = s.rate_heavy if kind == "heavy" else s.rate_general
        redis = request.app.state.container.redis
        bucket = int(__import__("time").time() // s.rate_window_sec)
        key = f"rl:{kind}:{p.tenant}:{p.label}:{bucket}"
        n = await redis.incr(key)
        if n == 1:
            await redis.expire(key, s.rate_window_sec + 1)
        response.headers["RateLimit-Limit"] = str(limit)
        response.headers["RateLimit-Remaining"] = str(max(0, limit - n))
        if n > limit:
            ttl = await redis.ttl(key)
            raise RateLimited("Rate limit exceeded", headers={"Retry-After": str(max(1, ttl))})
    return dep


_IDEM_KEY = re.compile(r"^[A-Za-z0-9_\-:.]{8,128}$")


async def idempotent(request: Request, tenant: str, scope: str, fingerprint_source, run: Callable[[], Awaitable[tuple[int, dict]]], required: bool = False):
    """Idempotency-Key protocol (Stripe style):
    * same key + same request  -> original response replayed (`Idempotent-Replay: true`), side-effects NOT repeated
    * same key + different body -> 422
    * same key while first request is still running -> 409
    * failed (non-2xx) attempts release the key so the client may retry"""
    key = request.headers.get("idempotency-key")
    if not key:
        if required:
            raise ValidationFailed("Idempotency-Key header is required for this operation")
        status, body = await run()
        return JSONResponse(body, status_code=status)
    if not _IDEM_KEY.match(key):
        raise ValidationFailed("Idempotency-Key must be 8-128 chars of [A-Za-z0-9_-:.]")
    redis = request.app.state.container.redis
    ttl = get_settings().idempotency_ttl_sec
    fp = crypto.sha256(json.dumps(fingerprint_source, sort_keys=True, default=str))
    rkey = f"idem:{tenant}:{scope}:{key}"
    if not await redis.set(rkey, json.dumps({"state": "in_progress", "fp": fp}), nx=True, ex=120):
        rec = json.loads(await redis.get(rkey) or "{}")
        if rec.get("fp") and rec["fp"] != fp:
            raise Unprocessable("Idempotency-Key was already used with a different request payload")
        if rec.get("state") == "done":
            return JSONResponse(rec["body"], status_code=rec["status"], headers={"Idempotent-Replay": "true"})
        raise Conflict("A request with this Idempotency-Key is still in progress", headers={"Retry-After": "2"})
    try:
        status, body = await run()
    except BaseException:
        await redis.delete(rkey)  # allow safe retry after failure
        raise
    await redis.set(rkey, json.dumps({"state": "done", "fp": fp, "status": status, "body": body}, default=str), ex=ttl)
    return JSONResponse(body, status_code=status)
