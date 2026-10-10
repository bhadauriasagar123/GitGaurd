"""Request schemas - strict (extra fields forbidden), length-bounded, enum-restricted."""
from __future__ import annotations

import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.firewall.extract import SOURCE_TYPES

SourceType = Literal["user", "web", "html", "pdf", "email", "markdown", "docx", "api", "ocr", "code", "image", "text"]
MAX_CHARS = 400_000


NUL = chr(0)  # Postgres cannot store NUL in text/JSONB


def _walk(v):
    if isinstance(v, str):
        if NUL in v:
            raise ValueError("NUL characters are not allowed")
    elif isinstance(v, dict):
        for k, x in v.items():
            _walk(k)
            _walk(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            _walk(x)
    return v


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _no_nul(cls, data):
        return _walk(data)


class ScanRequest(Strict):
    content: str | None = Field(None, max_length=MAX_CHARS)
    contentBase64: str | None = Field(None, max_length=4_000_000)
    sourceType: SourceType = "user"
    metadata: dict[str, str] | None = None
    sessionId: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-:.]{1,64}$")

    @field_validator("metadata")
    @classmethod
    def _meta(cls, v):
        if v and (len(v) > 20 or any(len(str(x)) > 2000 for x in v.values())):
            raise ValueError("metadata limited to 20 entries x 2000 chars")
        return v


class EgressRequest(Strict):
    text: str = Field(..., max_length=100_000)


class RegulationMeta(Strict):
    code: str = Field(..., pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{1,39}$")
    version: str = Field("1.0", pattern=r"^[A-Za-z0-9_.\-]{1,20}$")
    jurisdiction: str | None = Field(None, pattern=r"^[A-Za-z]{2,10}$")
    effectiveDate: date | None = None
    entityTypes: list[str] = Field(default_factory=lambda: ["all"], max_length=10)


class DocumentIn(Strict):
    kind: Literal["regulation", "policy", "control", "evidence"]
    title: str = Field(..., min_length=3, max_length=300)
    sourceType: SourceType = "text"
    content: str | None = Field(None, max_length=MAX_CHARS)
    contentBase64: str | None = Field(None, max_length=4_000_000)
    regulation: RegulationMeta | None = None
    sessionId: str | None = Field(None, pattern=r"^[A-Za-z0-9_\-:.]{1,64}$")

    def model_post_init(self, _):
        if bool(self.content) == bool(self.contentBase64):
            raise ValueError("provide exactly one of content / contentBase64")
        if self.kind in ("regulation", "policy") and not self.regulation:
            raise ValueError("regulation metadata (code, version) is required for regulation/policy documents")
        if self.contentBase64 and self.sourceType not in ("pdf", "docx"):
            raise ValueError("contentBase64 is only supported for sourceType pdf or docx")


class ProfileIn(Strict):
    entityType: str = Field("scheduled commercial bank", max_length=80)
    jurisdictions: list[str] = Field(default_factory=lambda: ["IN"], max_length=10)
    products: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("jurisdictions")
    @classmethod
    def _j(cls, v):
        if not all(re.fullmatch(r"[A-Za-z]{2,10}", x) for x in v):
            raise ValueError("jurisdiction codes must be 2-10 letters")
        return [x.upper() for x in v]


class WhatIfIn(Strict):
    changes: list[dict] = Field(..., min_length=1, max_length=20)

    @field_validator("changes")
    @classmethod
    def _c(cls, v):
        allowed = {"add_control", "remove_control", "update_control", "add_evidence", "change_regulation", "set_profile"}
        for ch in v:
            if ch.get("type") not in allowed:
                raise ValueError(f"change.type must be one of {sorted(allowed)}")
            if len(str(ch)) > 6000:
                raise ValueError("change too large")
        return v


class AskIn(Strict):
    question: str = Field(..., min_length=3, max_length=2000)
