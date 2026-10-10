"""Repository pattern: persistence concerns for encrypted documents."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.infra.orm import DocumentRow


class DocumentRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    @staticmethod
    def aad(tenant: str, doc_id: str) -> str:
        return f"{tenant}:{doc_id}"

    async def add(self, *, tenant: str, doc_id: str, plaintext: str, **meta) -> DocumentRow:
        row = DocumentRow(id=doc_id, tenant=tenant, box=crypto.encrypt(plaintext, self.aad(tenant, doc_id)),
                          sha256=crypto.sha256(plaintext), **meta)
        self.s.add(row)
        return row

    async def get(self, tenant: str, doc_id: str) -> DocumentRow | None:
        r = await self.s.get(DocumentRow, doc_id)
        return r if r and r.tenant == tenant else None  # tenant isolation enforced at the repository

    async def list(self, tenant: str, kind: str | None = None) -> list[DocumentRow]:
        q = select(DocumentRow).where(DocumentRow.tenant == tenant).order_by(DocumentRow.created_at)
        if kind:
            q = q.where(DocumentRow.kind == kind)
        return list((await self.s.execute(q)).scalars())

    async def delete(self, tenant: str, doc_id: str) -> bool:
        res = await self.s.execute(delete(DocumentRow).where(DocumentRow.id == doc_id, DocumentRow.tenant == tenant))
        return res.rowcount > 0

    async def delete_all(self, tenant: str) -> int:
        res = await self.s.execute(delete(DocumentRow).where(DocumentRow.tenant == tenant))
        return res.rowcount

    def plaintext(self, row: DocumentRow) -> str:
        return crypto.decrypt(row.box, self.aad(row.tenant, row.id))
