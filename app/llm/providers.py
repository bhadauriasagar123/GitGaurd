"""LLM provider strategies: any OpenAI-compatible API (free tiers such as Groq), Azure AI Foundry, or a deterministic offline
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


class OpenAICompatibleProvider(LLMProvider):
    """Any OpenAI-compatible chat-completions API: Groq, GitHub Models, Google Gemini, OpenRouter, Ollama, OpenAI."""
    _LABELS = {"groq.com": "groq", "models.github.ai": "github-models", "models.inference.ai.azure.com": "github-models",
               "generativelanguage.googleapis.com": "gemini", "openrouter.ai": "openrouter", "localhost": "ollama", "127.0.0.1": "ollama",
               "api.openai.com": "openai"}

    def __init__(self, s: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self.s, self._transport = s, transport
        host = httpx.URL(s.llm_base_url).host
        label = next((v for k, v in self._LABELS.items() if k in host), "openai-compatible")
        self.name = f"{label}/{s.llm_model}"

    async def complete(self, system: str, user: str, *, facts: dict | None = None) -> str:
        url = self.s.llm_base_url.rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {self.s.llm_api_key}"} if self.s.llm_api_key else {}
        body = {"model": self.s.llm_model, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": 0.1, "max_tokens": 700}
        try:
            async with httpx.AsyncClient(timeout=self.s.llm_timeout_sec, transport=self._transport) as c:
                r = await c.post(url, headers=headers, json=body)
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            raise DependencyUnavailable("LLM provider unavailable", {"provider": self.name, "error": type(e).__name__, "status": status})
        if not isinstance(text, str) or not text.strip():
            raise DependencyUnavailable("LLM provider returned an empty answer", {"provider": self.name})
        return text


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
