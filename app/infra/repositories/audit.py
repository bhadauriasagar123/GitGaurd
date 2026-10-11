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
        """Verify every entry's own HMAC and the prev-hash links, and say WHY a chain fails:
        * own-hash failures on a leading run of entries only  -> that segment was written under a different ENC_KEY
          (key changed, or the database already held another environment's audit trail); later entries verify and link correctly
        * a link break                                       -> an entry was removed, inserted or reordered
        * scattered own-hash failures                        -> those entries were modified after being written"""
        rows = list((await self.s.execute(select(AuditRow).where(AuditRow.tenant == tenant).order_by(AuditRow.seq))).scalars())
        prev = GENESIS
        own_bad: list[int] = []
        link_bad: list[int] = []
        for r in rows:
            ts = r.ts.replace(tzinfo=None).isoformat(timespec="seconds") if r.ts.tzinfo is None else r.ts.isoformat(timespec="seconds")
            expected = _digest(r.prev_hash, tenant, r.seq, ts, r.actor, r.action, r.resource, r.correlation_id, r.detail)
            # tolerate tz representation differences between SQLite/PostgreSQL by also trying the +00:00 form
            alt = _digest(r.prev_hash, tenant, r.seq, ts + "+00:00" if "+" not in ts else ts, r.actor, r.action, r.resource, r.correlation_id, r.detail)
            if r.hash not in (expected, alt):
                own_bad.append(r.seq)
            if r.prev_hash != prev:
                link_bad.append(r.seq)
            prev = r.hash
        if not own_bad and not link_bad:
            return {"valid": True, "entries": len(rows), "headHash": prev}
        first = min(own_bad + link_bad)
        out = {"valid": False, "entries": len(rows), "brokenAtSeq": first, "unverifiableSeqs": sorted(set(own_bad + link_bad))[:20]}
        if link_bad:
            out.update(diagnosis="LINK_BROKEN", hint=f"The chain link before entry {link_bad[0]} does not match: an entry was removed, inserted or reordered.")
        elif own_bad == list(range(1, len(own_bad) + 1)):
            whole = len(own_bad) == len(rows)
            out.update(diagnosis="WRITTEN_UNDER_DIFFERENT_KEY",
                       hint=("Every entry fails with the current ENC_KEY: this audit trail was written under a different key, or the database already held "
                             "another environment's data. " if whole else
                             f"Entries 1-{len(own_bad)} were written under a different ENC_KEY (key changed, or the database was shared with another environment); "
                             "entries after that verify and link correctly. ")
                       + "To start a clean, verifiable chain use a fresh database or a new tenant id (the part after the last ':' in API_KEYS).")
        else:
            out.update(diagnosis="ENTRIES_MODIFIED", hint=f"Entries {own_bad[:5]} do not match their recorded hash: they were modified after being written.")
        return out

    async def _tamper_for_tests(self, tenant: str, seq: int, action: str) -> None:  # pragma: no cover
        row = (await self.s.execute(select(AuditRow).where(AuditRow.tenant == tenant, AuditRow.seq == seq))).scalars().first()
        row.action = action
