"""Command and query message types (immutable)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class IngestDocument:
    tenant: str
    actor: str
    kind: str
    title: str
    source_type: str = "text"
    content: str | None = None
    content_b64: str | None = None
    regulation: dict | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class DeleteDocument:
    tenant: str
    doc_id: str


@dataclass(frozen=True)
class UpdateProfile:
    tenant: str
    profile: dict


@dataclass(frozen=True)
class LoadSample:
    tenant: str
    actor: str
    reset: bool = True
    dataset: str = "demo"


@dataclass(frozen=True)
class ResetTenant:
    tenant: str


# ---- queries
@dataclass(frozen=True)
class GetAnalysis:
    tenant: str


@dataclass(frozen=True)
class ListDocuments:
    tenant: str
    kind: str | None = None


@dataclass(frozen=True)
class GetDocument:
    tenant: str
    doc_id: str
    reveal: bool = False


@dataclass(frozen=True)
class GetImpactReports:
    tenant: str


@dataclass(frozen=True)
class GetTrend:
    tenant: str


@dataclass(frozen=True)
class GetTrace:
    tenant: str
    obligation_id: str


@dataclass(frozen=True)
class Simulate:
    tenant: str
    changes: list = field(default_factory=list)


@dataclass(frozen=True)
class Ask:
    tenant: str
    actor: str
    question: str


@dataclass(frozen=True)
class GetAudit:
    tenant: str
    limit: int = 100


@dataclass(frozen=True)
class VerifyAudit:
    tenant: str


@dataclass(frozen=True)
class GetProfile:
    tenant: str
