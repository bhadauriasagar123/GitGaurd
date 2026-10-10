"""Pure-ASGI middleware: correlation id, security headers, body-size limit, access log."""
from __future__ import annotations

import re
import secrets
import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import get_settings
from app.core.context import actor_var, correlation_id_var, tenant_var
from app.core.logging import get_logger

log = get_logger("access")
_CID_OK = re.compile(r"^[A-Za-z0-9._\-]{8,64}$")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"cross-origin-resource-policy", b"same-origin"),
    (b"permissions-policy", b"geolocation=(), microphone=(), camera=(), payment=()"),
    (b"strict-transport-security", b"max-age=63072000; includeSubDomains; preload"),
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
                                 b"object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"),
]
_DOCS_CSP = b"default-src 'self' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com"


class CorrelationSecurityMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.lower(): v for k, v in scope["headers"]}
        incoming = headers.get(b"x-correlation-id", b"").decode("latin1")
        cid = incoming if _CID_OK.match(incoming) else "req-" + secrets.token_hex(8)  # never trust unvalidated ids (log injection)
        correlation_id_var.set(cid)
        tenant_var.set("-")
        actor_var.set("-")
        scope.setdefault("state", {})["correlation_id"] = cid
        path, start, status = scope["path"], time.perf_counter(), [500]
        is_docs = path in ("/docs", "/redoc") or path.startswith("/docs/")

        async def send_wrapper(message: Message):
            if message["type"] == "http.response.start":
                status[0] = message["status"]
                hdrs = [(k, v) for k, v in message["headers"] if k.lower() not in (b"server", b"x-powered-by")]
                for k, v in SECURITY_HEADERS:
                    if is_docs and k == b"content-security-policy":
                        v = _DOCS_CSP
                    hdrs.append((k, v))
                hdrs.append((b"x-correlation-id", cid.encode()))
                message["headers"] = hdrs
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            if path not in ("/healthz", "/readyz"):
                log.info("request", method=scope["method"], path=path, status=status[0], ms=round((time.perf_counter() - start) * 1000, 1))


class BodyLimitMiddleware:
    """Rejects oversized bodies by Content-Length AND by counting streamed chunks (chunked uploads)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = get_settings().max_body_bytes
        cl = dict(scope["headers"]).get(b"content-length")
        if cl and cl.isdigit() and int(cl) > limit:
            return await self._reject(scope, receive, send, limit)
        seen = [0]

        async def limited_receive() -> Message:
            msg = await receive()
            if msg["type"] == "http.request":
                seen[0] += len(msg.get("body", b""))
                if seen[0] > limit:
                    raise _TooLarge()
            return msg

        try:
            await self.app(scope, limited_receive, send)
        except _TooLarge:
            await self._reject(scope, receive, send, limit)

    @staticmethod
    async def _reject(scope, receive, send, limit):
        import json

        cid = correlation_id_var.get()
        body = json.dumps({"type": "about:blank", "title": "Payload too large", "status": 413, "code": "PAYLOAD_TOO_LARGE",
                           "detail": f"Request body exceeds {limit} bytes", "correlationId": cid}).encode()
        await send({"type": "http.response.start", "status": 413, "headers": [(b"content-type", b"application/problem+json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})


class _TooLarge(Exception):
    pass
