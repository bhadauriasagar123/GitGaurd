"""LLM provider strategies. Production: Azure AI Foundry / Azure OpenAI deployment. Offline: deterministic
analyst so the platform works (and is testable) with zero external dependency."""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx

from app.core.config import Settings
from app.core.errors import DependencyUnavailable


class LLMProvider(ABC):
    name = "abstract"

    @abstractmethod
    async def complete(self, system: str, user: str, *, facts: dict | None = None) -> str: ...


class OfflineProvider(LLMProvider):
    """Rule-based answerer over the structured analysis (`facts`). No generation, so no hallucination."""
    name = "offline-deterministic"

    async def complete(self, system: str, user: str, *, facts: dict | None = None) -> str:
        f, q = facts or {}, user.lower()
        gaps = f.get("topGaps", [])
        if any(w in q for w in ("contradict", "conflict")):
            c = f.get("contradictions", [])
            return "No contradictions detected." if not c else "Detected conflicts: " + " | ".join(
                f"{x['type']} ({', '.join(b['regCode'] + ' ' + b['clause'] for b in x['between'])})" for x in c[:4])
        if any(w in q for w in ("change", "version", "impact")):
            ch = f.get("changes", [])
            return "No regulatory version changes on file." if not ch else " | ".join(
                f"{x['regCode']} {x['fromVersion']}->{x['toVersion']}: {len(x['modified'])} modified, {len(x['added'])} new, {len(x['removed'])} removed obligations" for x in ch)
        if any(w in q for w in ("prior", "first", "gap", "risk", "fix", "remed", "top")):
            if not gaps:
                return "No open gaps."
            return "Top priorities: " + " | ".join(
                f"[{g['band'].upper()} {g['riskScore']}] {g['title']} - {g['regCode']} cl.{g['clause']}: {g['summary']}" for g in gaps[:4])
        return (f"Compliance score {f.get('score')}%. {f.get('gapCount', 0)} open gaps "
                f"({f.get('bands', {})}); {f.get('contradictionCount', 0)} regulatory conflicts; {f.get('crossClusters', 0)} cross-regulation clusters.")


class FoundryProvider(LLMProvider):
    """Azure OpenAI-compatible chat completions (Azure AI Foundry deployments)."""
    name = "azure-foundry"

    def __init__(self, s: Settings):
        self.s = s

    async def complete(self, system: str, user: str, *, facts: dict | None = None) -> str:
        url = (f"{self.s.foundry_endpoint.rstrip('/')}/openai/deployments/{self.s.foundry_deployment}/chat/completions"
               f"?api-version={self.s.foundry_api_version}")
        body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.1, "max_tokens": 700}
        try:
            async with httpx.AsyncClient(timeout=self.s.llm_timeout_sec) as c:
                r = await c.post(url, headers={"api-key": self.s.foundry_key}, json=body)
                r.raise_for_status()
                return r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as e:
            raise DependencyUnavailable("LLM provider unavailable", {"provider": self.name, "error": type(e).__name__})
