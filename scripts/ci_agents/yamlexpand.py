"""Minimal emulation of Azure Pipelines COMPILE-TIME template expansion: `${{ if eq|ne(parameters.x, 'v') }}:` list blocks and
`${{ parameters.x }}` substitution. Enough to answer "what will Azure DevOps actually validate with the default parameters?"
(service connections, for example, are validated while PARSING, so runtime `condition:` does not hide them)."""
from __future__ import annotations

import re

_IF = re.compile(r"\$\{\{\s*if\s+(eq|ne)\(\s*parameters\.(\w+)\s*,\s*'([^']*)'\s*\)\s*\}\}")
_PARAM = re.compile(r"\$\{\{\s*parameters\.(\w+)\s*\}\}")


def defaults(doc: dict) -> dict:
    return {p["name"]: p.get("default", "") for p in (doc.get("parameters") or []) if isinstance(p, dict)}


def expand(node, params: dict):
    if isinstance(node, list):
        out = []
        for item in node:
            if isinstance(item, dict) and len(item) == 1:
                (k, v), = item.items()
                m = _IF.fullmatch(str(k))
                if m:
                    op, name, val = m.groups()
                    if (str(params.get(name)) == val) == (op == "eq"):
                        out.extend(expand(v, params) if isinstance(v, list) else [expand(v, params)])
                    continue
            out.append(expand(item, params))
        return out
    if isinstance(node, dict):
        return {k: expand(v, params) for k, v in node.items()}
    if isinstance(node, str):
        return _PARAM.sub(lambda m: str(params.get(m.group(1), "")), node)
    return node


def find_values(node, key: str):
    """Yield every value stored under `key` anywhere in the document."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from find_values(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from find_values(v, key)
