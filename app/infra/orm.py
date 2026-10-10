"""Relational tables (PostgreSQL) + JSONB document collections (the 'NoSQL' side of Postgres)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Json = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class DocumentRow(Base):
    """Encrypted source documents. `box` holds AES-256-GCM ciphertext; plaintext is never stored."""
    __tablename__ = "documents"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # regulation | control | evidence | policy
    title: Mapped[str] = mapped_column(String(300))
    code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String(40), nullable=True)
    effective_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    entity_types: Mapped[list] = mapped_column(Json, default=list)
    source_type: Mapped[str] = mapped_column(String(20), default="text")
    sha256: Mapped[str] = mapped_column(String(64))
    firewall: Mapped[dict] = mapped_column(Json, default=dict)
    box: Mapped[dict] = mapped_column(Json)
    created_by: Mapped[str] = mapped_column(String(80), default="-")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (Index("ix_documents_tenant_kind", "tenant", "kind"),)


class AuditRow(Base):
    """Append-only, hash-chained audit trail (tamper-evident)."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant: Mapped[str] = mapped_column(String(64), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(80))
    resource: Mapped[str] = mapped_column(String(200), default="")
    correlation_id: Mapped[str] = mapped_column(String(80), default="-")
    detail: Mapped[dict] = mapped_column(Json, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("tenant", "seq", name="uq_audit_tenant_seq"),)


class DocStoreRow(Base):
    """Schemaless JSONB collections: profiles, impact reports, compliance snapshots, quarantine."""
    __tablename__ = "doc_store"
    tenant: Mapped[str] = mapped_column(String(64), primary_key=True)
    collection: Mapped[str] = mapped_column(String(40), primary_key=True)
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    data: Mapped[dict] = mapped_column(Json)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    __table_args__ = (Index("ix_docstore_tenant_coll", "tenant", "collection"),)
