"""Admin / platform endpoints: health, profile, sample data, audit trail, system info."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request

from app.api.deps import Principal, idempotent, rate_limit, require
from app.api.schemas import ProfileIn
from app.core.config import get_settings
from app.core.logging import get_logger
from app.cqrs import messages as M
from app.firewall import egress

log = get_logger("readyz")
public = APIRouter(tags=["Platform"])
router = APIRouter(prefix="/api/v1", tags=["Administration"])


@public.get("/healthz", summary="Liveness")
async def healthz():
    return {"status": "ok"}


@public.get("/readyz", summary="Readiness - verifies PostgreSQL and Redis")
async def readyz(request: Request):
    c = request.app.state.container
    checks = {}
    for name, fn in (("postgres", c.db.ping), ("redis", c.redis.ping)):
        try:
            checks[name] = "up" if await fn() else "down"
        except Exception as e:  # noqa: BLE001 - report which dependency failed and why (type + short message, never credentials)
            checks[name] = "down"
            log.warning("readiness check failed", dependency=name, error=type(e).__name__, detail=str(e)[:200])
    ok = all(v == "up" for v in checks.values())
    from fastapi.responses import JSONResponse
    return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)


@router.get("/whoami")
async def whoami(p: Principal = Depends(require("viewer"))):
    return {"tenant": p.tenant, "role": p.role}


@router.get("/profile", summary="Bank profile used for applicability")
async def get_profile(request: Request, p: Principal = Depends(require("viewer"))):
    return await request.app.state.container.queries.dispatch(M.GetProfile(p.tenant))


@router.put("/profile")
async def put_profile(body: ProfileIn, request: Request, p: Principal = Depends(require("analyst")), _=Depends(rate_limit())):
    return await request.app.state.container.commands.dispatch(M.UpdateProfile(p.tenant, body.model_dump()))


@router.post("/sample/load", summary="Load a dataset through the full firewalled pipeline (idempotent). dataset=real: public-regulation pack; demo: fictional test fixture")
async def load_sample(request: Request, dataset: Literal["demo", "real"] = "demo", p: Principal = Depends(require("analyst")), _=Depends(rate_limit("heavy"))):
    c = request.app.state.container

    async def run():
        return 200, await c.commands.dispatch(M.LoadSample(p.tenant, p.label, dataset=dataset))

    return await idempotent(request, p.tenant, "sample", {"sample": True, "dataset": dataset}, run)


@router.post("/admin/reset", summary="Delete all tenant data")
async def reset(request: Request, p: Principal = Depends(require("admin")), _=Depends(rate_limit("heavy"))):
    return await request.app.state.container.commands.dispatch(M.ResetTenant(p.tenant))


@router.get("/audit", summary="Tamper-evident audit trail")
async def audit(request: Request, limit: int = 100, p: Principal = Depends(require("admin")), _=Depends(rate_limit())):
    return await request.app.state.container.queries.dispatch(M.GetAudit(p.tenant, max(1, min(limit, 500))))


@router.get("/audit/verify", summary="Verify audit hash chain integrity")
async def audit_verify(request: Request, p: Principal = Depends(require("admin")), _=Depends(rate_limit())):
    return await request.app.state.container.queries.dispatch(M.VerifyAudit(p.tenant))


@router.get("/system/info", summary="Runtime topology (no secrets)")
async def system_info(request: Request, p: Principal = Depends(require("admin"))):
    c = request.app.state.container
    s = get_settings()
    return {"env": s.env, "database": c.db.engine.dialect.name, "redis": "real" if not s.redis_url.startswith("fakeredis") else "fakeredis(dev)",
            "llmProvider": c.llm.name, "promptVault": egress.vault.status(),
            "firewallThresholds": {"block": s.fw_block, "sanitize": s.fw_sanitize}}
