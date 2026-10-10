"""Firewall + document ingestion endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.deps import Principal, idempotent, rate_limit, require
from app.api.schemas import DocumentIn, EgressRequest, ScanRequest
from app.core.config import get_settings
from app.core.errors import PayloadTooLarge
from app.cqrs import messages as M
from app.firewall import egress, rules
from app.sample import data as sample

router = APIRouter(prefix="/api/v1")


@router.post("/firewall/scan", tags=["Prompt Injection Firewall"], summary="Scan any content before it reaches an AI agent")
async def scan(body: ScanRequest, request: Request, p: Principal = Depends(require("analyst")), _=Depends(rate_limit("heavy"))):
    if not (body.content or body.contentBase64):
        from app.core.errors import ValidationFailed
        raise ValidationFailed("provide content or contentBase64")
    if body.content and len(body.content) > get_settings().max_content_chars:
        raise PayloadTooLarge("content too long")
    fw = request.app.state.container.firewall
    try:
        res = await fw.scan(content=body.content, content_b64=body.contentBase64, source_type=body.sourceType, metadata=body.metadata,
                            session_id=body.sessionId, tenant=p.tenant)
    except ValueError as e:  # corrupt docx/pdf/base64
        from app.core.errors import Unprocessable
        raise Unprocessable(f"could not parse {body.sourceType} content: {type(e).__name__}")
    return res


@router.post("/firewall/egress", tags=["Prompt Injection Firewall"], summary="Inspect model OUTPUT for prompt/document/secret leakage")
async def egress_check(body: EgressRequest, request: Request, p: Principal = Depends(require("analyst")), _=Depends(rate_limit())):
    c = request.app.state.container
    async with c.db.uow() as u:
        protected = [u.documents.plaintext(r) for r in await u.documents.list(p.tenant)]
    return egress.inspect(body.text, protected)


@router.get("/firewall/catalog", tags=["Prompt Injection Firewall"], summary="Attack classes, rule inventory and vault status")
async def catalog(p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    per: dict[str, int] = {}
    for r in rules.RULES:
        per[r.category] = per.get(r.category, 0) + 1
    return {"attackClasses": [{"category": c, "severity": rules.SEVERITY[c], "rules": per.get(c, 0)} for c in rules.CATEGORIES],
            "totalRules": len(rules.RULES), "promptVault": egress.vault.status(),
            "layers": ["source adapters", "canonicalisation", "decoders", "directive rules", "indirect/encoded elevation", "session risk memory", "sanitiser + spotlighting", "egress guard"]}


@router.get("/firewall/samples", tags=["Prompt Injection Firewall"], summary="Ready-made attack payloads for the demo")
async def attack_samples(p: Principal = Depends(require("viewer"))):
    return sample.ATTACK_DOCS


@router.post("/documents", status_code=201, tags=["Ingestion"], summary="Ingest a regulation / control framework / evidence (firewalled, idempotent)")
async def ingest(body: DocumentIn, request: Request, p: Principal = Depends(require("analyst")), _=Depends(rate_limit("heavy"))):
    c = request.app.state.container
    if body.content and len(body.content) > get_settings().max_content_chars:
        raise PayloadTooLarge("content too long")

    async def run():
        reg = body.regulation.model_dump(mode="json") if body.regulation else None
        try:
            res = await c.commands.dispatch(M.IngestDocument(p.tenant, p.label, body.kind, body.title, body.sourceType, body.content,
                                                             body.contentBase64, reg, body.sessionId))
        except ValueError as e:
            from app.core.errors import Unprocessable
            raise Unprocessable(f"could not parse {body.sourceType} content: {type(e).__name__}")
        return 201, res

    return await idempotent(request, p.tenant, "documents", body.model_dump(mode="json"), run)


@router.get("/documents", tags=["Ingestion"])
async def list_docs(request: Request, kind: str | None = None, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    return await request.app.state.container.queries.dispatch(M.ListDocuments(p.tenant, kind))


@router.get("/documents/{doc_id}", tags=["Ingestion"], summary="Metadata only; reveal=true is admin-only and audited")
async def get_doc(doc_id: str, request: Request, reveal: bool = False, p: Principal = Depends(require("viewer")), _=Depends(rate_limit())):
    if reveal and p.role != "admin":
        from app.core.errors import Forbidden
        raise Forbidden("Only admins may reveal document content (every reveal is audited)")
    return await request.app.state.container.queries.dispatch(M.GetDocument(p.tenant, doc_id, reveal))


@router.delete("/documents/{doc_id}", tags=["Ingestion"])
async def delete_doc(doc_id: str, request: Request, p: Principal = Depends(require("admin")), _=Depends(rate_limit())):
    return await request.app.state.container.commands.dispatch(M.DeleteDocument(p.tenant, doc_id))
