"""Redis-backed conversation risk memory - catches multi-step jailbreaks and payload splitting
that no single message reveals ("crescendo" attacks)."""
from __future__ import annotations

import json
import time

SESSION_TTL = 3600
MAX_HISTORY = 10


class SessionRiskTracker:
    def __init__(self, redis):
        self._r = redis

    @staticmethod
    def _key(tenant: str, sid: str) -> str:
        return f"fw:sess:{tenant}:{sid}"

    async def history(self, tenant: str, sid: str) -> list[dict]:
        raw = await self._r.lrange(self._key(tenant, sid), 0, -1)
        out = []
        for r in raw:
            try:
                out.append(json.loads(r))
            except ValueError:
                continue
        return out

    async def record(self, tenant: str, sid: str, score: float, categories: list[str]) -> None:
        k = self._key(tenant, sid)
        await self._r.rpush(k, json.dumps({"t": int(time.time()), "s": round(score, 3), "c": categories}))
        await self._r.ltrim(k, -MAX_HISTORY, -1)
        await self._r.expire(k, SESSION_TTL)

    @staticmethod
    def escalation(prior: list[dict], current: float) -> tuple[float, str] | None:
        """Return (weight, reason) if the conversation trajectory is itself an attack."""
        scores = [h["s"] for h in prior] + [current]
        suspicious = [s for s in scores if s >= 0.2]
        decayed = sum(s * (0.85 ** (len(scores) - 1 - i)) for i, s in enumerate(scores))
        if len(suspicious) >= 3 and sum(suspicious) >= 1.0:
            return min(0.92, 0.5 + 0.1 * len(suspicious)), f"{len(suspicious)} suspicious turns, cumulative risk {sum(suspicious):.2f}"
        last4 = scores[-4:]
        if len(last4) == 4 and all(b > a for a, b in zip(last4, last4[1:])) and last4[-1] >= 0.3:
            return 0.65, "monotonically escalating risk across last 4 turns (crescendo)"
        if decayed >= 1.5:
            return 0.8, f"decayed cumulative risk {decayed:.2f}"
        return None
