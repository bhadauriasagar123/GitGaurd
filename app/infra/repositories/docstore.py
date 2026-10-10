"""Document-store repository over JSONB (profiles, impact reports, snapshots, quarantine)."""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.orm import DocStoreRow, utcnow


class DocStoreRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def put(self, tenant: str, collection: str, key: str, data: dict) -> None:
        row = await self.s.get(DocStoreRow, (tenant, collection, key))
        if row:
            row.data, row.updated_at = data, utcnow()
        else:
            self.s.add(DocStoreRow(tenant=tenant, collection=collection, key=key, data=data))

    async def get(self, tenant: str, collection: str, key: str) -> dict | None:
        row = await self.s.get(DocStoreRow, (tenant, collection, key))
        return row.data if row else None

    async def list(self, tenant: str, collection: str, limit: int = 100) -> list[dict]:
        q = (select(DocStoreRow).where(DocStoreRow.tenant == tenant, DocStoreRow.collection == collection)
             .order_by(DocStoreRow.updated_at.desc()).limit(limit))
        return [r.data for r in (await self.s.execute(q)).scalars()]

    async def delete_collection(self, tenant: str, collection: str | None = None) -> None:
        q = delete(DocStoreRow).where(DocStoreRow.tenant == tenant)
        if collection:
            q = q.where(DocStoreRow.collection == collection)
        await self.s.execute(q)
