"""Unit of Work: one transaction spanning all repositories; commit on success, rollback on error."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra.repositories.audit import AuditRepository
from app.infra.repositories.docstore import DocStoreRepository
from app.infra.repositories.documents import DocumentRepository


class UnitOfWork:
    def __init__(self, factory: async_sessionmaker[AsyncSession]):
        self._factory = factory

    async def __aenter__(self) -> "UnitOfWork":
        self.session = self._factory()
        self.documents = DocumentRepository(self.session)
        self.audit = AuditRepository(self.session)
        self.docstore = DocStoreRepository(self.session)
        return self

    async def __aexit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()

    async def flush(self):
        await self.session.flush()
