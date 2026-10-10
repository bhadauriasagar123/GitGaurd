"""Factory: choose the LLM strategy from configuration."""
from __future__ import annotations

from app.core.config import Settings
from app.llm.providers import FoundryProvider, LLMProvider, OfflineProvider


def build_provider(s: Settings) -> LLMProvider:
    if s.foundry_endpoint and s.foundry_key:
        return FoundryProvider(s)
    return OfflineProvider()
