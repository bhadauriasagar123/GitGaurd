"""Compliance intelligence endpoints (queries) + what-if + assistant."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import Principal, idempotent, rate_limit, require
from app.api.schemas import AskIn, WhatIfIn
from app.cqrs import messages as M

router = APIRouter(prefix="/api/v1", tags=["Compliance Intelligence"])
BANDS = ["low", "medium", "high", "critical"]


async def _analysis(request: Request, p: Principal) -> dict:
    return await request.app.state.container.queries.dispatch(M.GetAnalysis(p.tenant))


@router.get("/analysis/summary", summary="Score, counts, headline findings (features 7, 8, 9)")
async def summary(request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    a = await _analysis(request, p)
    return {"asOf": a["asOf"], "complianceScore": a["complianceScore"], "counts": a["counts"], "profile": a["profile"],
            "topGaps": [{"id": g["id"], "title": g["title"], "regCode": g["regCode"], "clause": g["clause"], "risk": g["risk"], "detail": g["detail"]} for g in a["gaps"][:5]],
            "contradictions": len(a["contradictions"]), "crossRegulationClusters": len(a["crossRegulation"]),
            "regulatoryChanges": [{"regCode": c["regCode"], "from": c["fromVersion"], "to": c["toVersion"], "modified": len(c["modified"]), "added": len(c["added"]), "removed": len(c["removed"])} for c in a["changes"]],
            "readModelCache": a.get("_cache")}


@router.get("/obligations", summary="Extracted obligations incl. applicability (features 1, 3)")
async def obligations(request: Request, regCode: str | None = None, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    a = await _analysis(request, p)
    return [o for o in a["obligations"] if not regCode or o["regCode"] == regCode]


@router.get("/controls", summary="Control framework with effectiveness (features 4, 6)")
async def controls(request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    a = await _analysis(request, p)
    eff = {e["controlId"]: e for e in a["controlEffectiveness"]}
    return [{**c, "effectiveness": eff[c["id"]]} for c in a["controls"]]


@router.get("/assessments", summary="Regulation -> control mapping and evidence-based status (features 5, 7)")
async def assessments(request: Request, status: str | None = None, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    a = await _analysis(request, p)
    return [x for x in a["assessments"] if not status or x["status"] == status]


@router.get("/gaps", summary="Risk-prioritised gaps with remediation (features 8, 9, 10)")
async def gaps(request: Request, minBand: str = "low", p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    a = await _analysis(request, p)
    floor = BANDS.index(minBand) if minBand in BANDS else 0
    return [g for g in a["gaps"] if BANDS.index(g["risk"]["band"]) >= floor]


@router.get("/changes", summary="Regulatory change intelligence - version diffs (feature 2)")
async def changes(request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    return (await _analysis(request, p))["changes"]


@router.get("/impact", summary="Autonomous regulatory impact reports (feature 11)")
async def impact(request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    return await request.app.state.container.queries.dispatch(M.GetImpactReports(p.tenant))


@router.get("/cross-regulation", summary="Overlapping obligations across regulations (feature 13)")
async def cross(request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    return (await _analysis(request, p))["crossRegulation"]


@router.get("/contradictions", summary="Conflicting regulatory requirements (feature 14)")
async def contradictions(request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    return (await _analysis(request, p))["contradictions"]


@router.get("/trace/{obligation_id:path}", summary="End-to-end traceability chain regulation -> ... -> monitoring")
async def trace(obligation_id: str, request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    return await request.app.state.container.queries.dispatch(M.GetTrace(p.tenant, obligation_id))


@router.get("/monitoring/trend", summary="Ongoing monitoring - compliance score history")
async def trend(request: Request, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    return await request.app.state.container.queries.dispatch(M.GetTrend(p.tenant))


@router.post("/whatif", summary="What-if / simulation (feature 12) - never mutates data")
async def whatif(body: WhatIfIn, request: Request, p: Principal = Depends(require("analyst")), _=Depends(rate_limit("heavy"))):
    return await request.app.state.container.queries.dispatch(M.Simulate(p.tenant, body.changes))


@router.post("/assistant/ask", summary="Firewall-guarded compliance copilot (input AND output screened)")
async def ask(body: AskIn, request: Request, p: Principal = Depends(require("analyst")), _=Depends(rate_limit("heavy"))):
    return await request.app.state.container.queries.dispatch(M.Ask(p.tenant, p.label, body.question))
