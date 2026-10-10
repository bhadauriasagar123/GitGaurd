"""Application factory."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from redis.exceptions import RedisError
from sqlalchemy.exc import InterfaceError, OperationalError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.middleware import BodyLimitMiddleware, CorrelationSecurityMiddleware
from app.api.routers import admin, analysis, ingest
from app.container import build_container
from app.core.config import get_settings
from app.core.context import correlation_id_var
from app.core.errors import AppError
from app.core.logging import get_logger, setup_logging
from app.infra.db import Database
from app.infra.redis_client import close_redis

log = get_logger("app")
STATIC = Path(__file__).resolve().parent.parent / "static"


def problem(status: int, code: str, title: str, detail=None, headers: dict | None = None, **extra) -> JSONResponse:
    body = {"type": f"https://regguard.example/errors/{code.lower()}", "title": title, "status": status, "code": code,
            "correlationId": correlation_id_var.get()}
    if detail is not None:
        body["detail"] = detail
    body.update(extra)
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


def create_app() -> FastAPI:
    s = get_settings()
    setup_logging()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = await build_container()
        log.info("started", env=s.env, db=app.state.container.db.engine.dialect.name, llm=app.state.container.llm.name)
        yield
        await close_redis()
        await Database.dispose()

    app = FastAPI(title=s.app_name, version="1.0.0", lifespan=lifespan,
                  description="Agentic banking regulatory compliance platform (Problem 1) protected end-to-end by a Prompt Injection Firewall (Problem 2).",
                  docs_url="/docs" if s.docs_enabled else None, redoc_url=None, openapi_url="/openapi.json" if s.docs_enabled else None)

    # ---- exception handling: every error is RFC 7807 + correlation id, internals never leak
    @app.exception_handler(AppError)
    async def _app_error(_: Request, e: AppError):
        return problem(e.status, e.code, e.message, e.details, e.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, e: RequestValidationError):
        errs = [{"field": ".".join(str(x) for x in err["loc"][1:]), "message": err["msg"]} for err in e.errors()][:10]
        return problem(400, "VALIDATION_ERROR", "Request validation failed", errs)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, e: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(e.status_code, "HTTP_ERROR")
        return problem(e.status_code, code, str(e.detail), headers=getattr(e, "headers", None))

    @app.exception_handler(RedisError)
    async def _redis_down(_: Request, e: RedisError):
        log.error("redis failure", error=type(e).__name__)
        return problem(503, "DEPENDENCY_UNAVAILABLE", "Cache/limiter backend unavailable - failing closed", headers={"Retry-After": "5"})

    @app.exception_handler(SQLAlchemyError)
    async def _db_down(_: Request, e: SQLAlchemyError):
        log.error("database failure", error=type(e).__name__)
        transient = isinstance(e, (OperationalError, InterfaceError, TimeoutError)) or getattr(e, "connection_invalidated", False)
        if transient:
            return problem(503, "DEPENDENCY_UNAVAILABLE", "Database temporarily unavailable", headers={"Retry-After": "5"})
        return problem(500, "INTERNAL_ERROR", "Internal server error", "The error was logged; quote the correlationId to support.")

    @app.exception_handler(asyncio.TimeoutError)
    async def _timeout(_: Request, e: Exception):
        return problem(504, "UPSTREAM_TIMEOUT", "An upstream dependency timed out", headers={"Retry-After": "5"})

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, e: Exception):
        log.exception("unhandled error", error=type(e).__name__)
        return problem(500, "INTERNAL_ERROR", "Internal server error", "The error was logged; quote the correlationId to support.")

    app.include_router(admin.public)
    app.include_router(admin.router)
    app.include_router(ingest.router)
    app.include_router(analysis.router)

    if s.cors_list:
        app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_methods=["GET", "POST", "PUT", "DELETE"],
                           allow_headers=["Authorization", "X-API-Key", "Content-Type", "Idempotency-Key", "X-Correlation-ID"],
                           expose_headers=["X-Correlation-ID", "Idempotent-Replay", "RateLimit-Remaining", "Retry-After"], max_age=600)
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(CorrelationSecurityMiddleware)  # outermost: correlation id exists for every response, even errors

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=STATIC), name="static")

        @app.get("/", include_in_schema=False)
        async def index():
            return FileResponse(STATIC / "index.html")

        @app.get("/config.json", include_in_schema=False)
        async def ui_config():
            return {"demoKey": "demo-admin-key" if not s.is_prod and not s.api_keys else None}

    return app


app = create_app()
