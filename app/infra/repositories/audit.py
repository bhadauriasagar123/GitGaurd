"""Hash-chained append-only audit log. Each entry's hash covers the previous hash, so any
edit/deletion/reordering breaks verification from that point on."""
from __future__ import annotations

import json

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.context import actor_var, correlation_id_var
from app.infra.orm import AuditRow, utcnow

GENESIS = "0" * 64


def _digest(prev: str, tenant: str, seq: int, ts: str, actor: str, action: str, resource: str, cid: str, detail: dict) -> str:
    payload = json.dumps([prev, tenant, seq, ts, actor, action, resource, cid, detail], sort_keys=True, default=str)
    return crypto.hmac_hex(payload)


class AuditRepository:
    def __init__(self, session: AsyncSession):
        self.s = session

    async def append(self, tenant: str, action: str, resource: str = "", detail: dict | None = None) -> AuditRow:
        if self.s.bind.dialect.name == "postgresql":  # serialise seq allocation per tenant until commit
            await self.s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:t))"), {"t": f"audit:{tenant}"})
        last = (await self.s.execute(select(AuditRow).where(AuditRow.tenant == tenant).order_by(AuditRow.seq.desc()).limit(1))).scalars().first()
        seq, prev = (last.seq + 1, last.hash) if last else (1, GENESIS)
        ts = utcnow()
        actor, cid, detail = actor_var.get(), correlation_id_var.get(), detail or {}
        row = AuditRow(tenant=tenant, seq=seq, ts=ts, actor=actor, action=action, resource=resource, correlation_id=cid,
                       detail=detail, prev_hash=prev,
                       hash=_digest(prev, tenant, seq, ts.isoformat(timespec="seconds"), actor, action, resource, cid, detail))
        self.s.add(row)
        return row

    async def list(self, tenant: str, limit: int = 100) -> list[AuditRow]:
        q = select(AuditRow).where(AuditRow.tenant == tenant).order_by(AuditRow.seq.desc()).limit(limit)
        return list((await self.s.execute(q)).scalars())

    async def count(self, tenant: str) -> int:
        return (await self.s.execute(select(func.count()).select_from(AuditRow).where(AuditRow.tenant == tenant))).scalar_one()

    async def verify(self, tenant: str) -> dict:
        rows = list((await self.s.execute(select(AuditRow).where(AuditRow.tenant == tenant).order_by(AuditRow.seq))).scalars())
        prev = GENESIS
        for r in rows:
            ts = r.ts.replace(tzinfo=None).isoformat(timespec="seconds") if r.ts.tzinfo is None else r.ts.isoformat(timespec="seconds")
            expected = _digest(prev, tenant, r.seq, ts, r.actor, r.action, r.resource, r.correlation_id, r.detail)
            # tolerate tz representation differences between SQLite/PostgreSQL by also trying the +00:00 form
            alt = _digest(prev, tenant, r.seq, ts + "+00:00" if "+" not in ts else ts, r.actor, r.action, r.resource, r.correlation_id, r.detail)
            if r.prev_hash != prev or r.hash not in (expected, alt):
                return {"valid": False, "entries": len(rows), "brokenAtSeq": r.seq}
            prev = r.hash
        return {"valid": True, "entries": len(rows), "headHash": prev}

    async def _tamper_for_tests(self, tenant: str, seq: int, action: str) -> None:  # pragma: no cover
        row = (await self.s.execute(select(AuditRow).where(AuditRow.tenant == tenant, AuditRow.seq == seq))).scalars().first()
        row.action = action
