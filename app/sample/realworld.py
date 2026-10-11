"""Regulatory dataset built from public regulations (CERT-In 2022, RBI CSF 2016, RBI KYC MD 2016, DPDP Act 2023 + Rules 2025, GDPR)
plus a production-format bank control framework and testing evidence. Files live in app/sample/dataset/ and can also be uploaded
one by one through the UI. Evidence dates are shifted so the register is always as fresh as on the manifest's "asOf" date."""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

DIR = Path(__file__).resolve().parent / "dataset"


@lru_cache(maxsize=1)
def manifest() -> dict:
    return json.loads((DIR / "manifest.json").read_text(encoding="utf8"))


def as_of() -> date:
    return date.fromisoformat(manifest()["asOf"])


def _shift_evidence(text: str, today: date) -> str:
    delta = today - as_of()
    rows = json.loads(text)
    for r in rows:
        r["date"] = (date.fromisoformat(r["date"]) + delta).isoformat()
    return json.dumps(rows, indent=1)


def build(today: date | None = None) -> list[dict]:
    today = today or date.today()
    docs = []
    for item in manifest()["load_order"]:
        content = (DIR / item["file"]).read_text(encoding="utf8")
        if item["kind"] == "evidence":
            content = _shift_evidence(content, today)
        doc = {k: item[k] for k in ("kind", "title", "sourceType")}
        doc["content"] = content
        if item.get("regulation"):
            doc["regulation"] = item["regulation"]
        docs.append(doc)
    return docs


PROFILE = manifest()["profile"]
