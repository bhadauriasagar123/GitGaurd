"""Generate docs/API.md from the live OpenAPI schema:  python -m scripts.gen_api_docs"""
from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("ENV", "dev")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "fakeredis://")

from app.main import create_app  # noqa: E402


def main() -> None:
    spec = create_app().openapi()
    rows = []
    for path, ops in sorted(spec["paths"].items()):
        for method, op in ops.items():
            rows.append((op.get("tags", ["misc"])[0], path, method.upper(), op.get("summary", ""), 
                         ", ".join(p["name"] for p in op.get("parameters", []) if p["in"] in ("query",))))
    out = ["# API reference", "",
           f"Generated from the OpenAPI schema (`{spec['info']['title']} v{spec['info']['version']}`). Interactive docs: `/docs` (dev/staging).", "",
           "**Auth:** header `X-API-Key: <key>` (roles: `viewer` < `analyst` < `admin`; each key is bound to one tenant). "
           "**Writes:** send `Idempotency-Key: <uuid>` (replays return the original response). "
           "**Tracing:** every response carries `X-Correlation-Id`. **Errors:** RFC 7807 `application/problem+json`.", ""]
    tag = None
    for t, path, m, summ, q in sorted(rows):
        if t != tag:
            out += ["", f"## {t}", "", "| Method | Path | Summary | Query |", "|---|---|---|---|"]
            tag = t
        out.append(f"| {m} | `{path}` | {summ} | {q} |")
    Path("docs/API.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(rows)} operations")


if __name__ == "__main__":
    main()
