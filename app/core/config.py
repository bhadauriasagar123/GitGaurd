"""Application settings - a cached singleton (12-factor: everything comes from env vars)."""
from __future__ import annotations

import hashlib
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@lru_cache(maxsize=1)
def _dev_key() -> bytes:
    return hashlib.scrypt(b"regguard-dev-only", salt=b"regguard-salt", n=2**14, r=8, p=1, dklen=32)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: str = "dev"  # dev | test | production
    app_name: str = "RegGuard Shield"
    port: int = 8000

    # Persistence: PostgreSQL (relational tables + JSONB document collections) and Redis.
    database_url: str = "sqlite+aiosqlite:///./regguard.db"
    redis_url: str = "fakeredis://"  # dev/test fallback; production requires a real Redis (rediss://...)

    # Security
    api_keys: str = ""  # "key:role:tenant,key2:analyst:tenant"
    enc_key: str = ""  # 64 hex chars (32 bytes) AES-256-GCM key; in Azure sourced from Key Vault
    cors_origins: str = ""
    docs_enabled: bool = True
    max_body_bytes: int = 3_000_000
    max_content_chars: int = 400_000

    # Rate limiting (fixed window in Redis)
    rate_window_sec: int = 60
    rate_general: int = 240
    rate_heavy: int = 40

    idempotency_ttl_sec: int = 86_400

    # Prompt Injection Firewall thresholds
    fw_block: float = 0.75
    fw_sanitize: float = 0.35
    fw_ml_enabled: bool = True
    fw_ml_threshold: float = 0.8  # P(attack) above which the learned model contributes evidence

    # LLM (Azure AI Foundry / Azure OpenAI deployment) - optional, firewall-guarded
    foundry_endpoint: str = ""  # https://<resource>.openai.azure.com  or  https://<resource>.services.ai.azure.com
    foundry_key: str = ""
    foundry_deployment: str = "gpt-4o-mini"
    foundry_api_version: str = "2024-10-21"
    llm_timeout_sec: float = 20.0

    @property
    def is_prod(self) -> bool:
        return self.env == "production"

    @model_validator(mode="after")
    def _prod_guards(self) -> "Settings":
        if self.is_prod:
            if not self.api_keys:
                raise ValueError("API_KEYS must be set in production")
            if len(self.enc_key) != 64:
                raise ValueError("ENC_KEY (64 hex chars) must be set in production")
            if self.redis_url.startswith("fakeredis"):
                raise ValueError("REDIS_URL must point at a real Redis in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("DATABASE_URL must point at PostgreSQL in production")
        return self

    # ---- derived -------------------------------------------------------
    def key_ring(self) -> list[dict]:
        """Hashed API keys. Raw keys are never retained after startup."""
        raw = self.api_keys or "demo-admin-key:admin:demo-bank"
        ring = []
        for entry in raw.split(","):
            parts = entry.strip().split(":")
            if len(parts) != 3:
                raise ValueError("API_KEYS entries must be key:role:tenant")
            key, role, tenant = parts
            if role not in ("admin", "analyst", "viewer"):
                raise ValueError(f"invalid role {role}")
            if self.is_prod and len(key) < 24:
                raise ValueError("API keys must be >= 24 chars in production")
            ring.append({"hash": hashlib.sha256(key.encode()).hexdigest(), "role": role, "tenant": tenant})
        return ring

    def enc_key_bytes(self) -> bytes:
        if self.enc_key:
            return bytes.fromhex(self.enc_key)
        return _dev_key()  # scrypt is deliberately slow: derive once, never per call

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:  # used by tests
    get_settings.cache_clear()
