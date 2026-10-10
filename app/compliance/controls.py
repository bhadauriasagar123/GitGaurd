"""Features 4 & 7 (input side): understand the bank's control framework and its evidence.

Accepts either JSON arrays or semi-structured text blocks:

    Control ID: C-001
    Title: ...
    Description: ...
    Owner: ...  Type: preventive|detective|corrective  Frequency: quarterly  Automation: automated|manual
"""
from __future__ import annotations

import json
import re
from datetime import date

from app.compliance import text as T

_FIELD = re.compile(r"^\s*([A-Za-z][A-Za-z _/-]{1,30}?)\s*:\s*(.*)$")


def _blocks(text: str, start_key: str) -> list[dict]:
    blocks, cur, last = [], None, None
    for line in text.splitlines():
        m = _FIELD.match(line)
        if m:
            key = re.sub(r"[ _/-]+", "", m.group(1).lower())
            if key == start_key:
                cur = {}
                blocks.append(cur)
            if cur is not None:
                cur[key] = m.group(2).strip()
                last = key
        elif cur is not None and line.strip() and last:
            cur[last] += " " + line.strip()
    return blocks


def _maybe_json(text: str):
    t = text.lstrip()
    if t.startswith("[") or t.startswith("{"):
        try:
            data = json.loads(t)
            return data if isinstance(data, list) else data.get("items") or [data]
        except ValueError:
            return None
    return None


def parse_controls(text: str) -> list[dict]:
    raw = _maybe_json(text)
    if raw is None:
        raw = _blocks(text, "controlid")
        for r in raw:
            r["id"] = r.pop("controlid")
    controls = []
    for r in raw:
        r = {re.sub(r"[ _/-]+", "", str(k).lower()): v for k, v in r.items()}
        cid = str(r.get("id") or r.get("controlid") or "").strip()
        if not cid:
            continue
        desc = str(r.get("description") or "")
        title = str(r.get("title") or r.get("name") or cid)
        blob = f"{title}. {desc}"
        freq_txt = str(r.get("frequency") or "")
        controls.append({
            "id": cid, "title": title, "description": desc, "owner": r.get("owner") or None,
            "type": (str(r.get("type") or "preventive").lower().split("/")[0].strip()),
            "automation": str(r.get("automation") or "manual").lower(),
            "frequencyDays": T.frequency_days(freq_txt) or T.frequency_days(blob),
            "frequencyLabel": freq_txt or None,
            "deadlineHours": T.deadline_hours(blob),
            "retentionMinHours": T.retention(blob).get("minHours"),
            "retentionMaxHours": T.retention(blob).get("maxHours"),
            "topics": T.topics_of(blob), "text": blob,
        })
    return controls


def parse_evidence(text: str) -> list[dict]:
    raw = _maybe_json(text)
    if raw is None:
        raw = _blocks(text, "evidenceid")
        for r in raw:
            r["id"] = r.pop("evidenceid")
    out = []
    for r in raw:
        r = {re.sub(r"[ _/-]+", "", str(k).lower()): v for k, v in r.items()}
        eid = str(r.get("id") or "").strip()
        ctrl = str(r.get("control") or r.get("controlid") or "").strip()
        if not eid or not ctrl:
            continue
        try:
            d = date.fromisoformat(str(r.get("date"))[:10])
        except ValueError:
            continue
        result = str(r.get("result") or "pass").lower()
        try:
            exc = int(float(r.get("exceptions") or 0))
        except ValueError:
            exc = 0
        out.append({"id": eid, "controlId": ctrl, "date": d.isoformat(), "result": "pass" if result.startswith("pass") else
                    "partial" if result.startswith("part") else "fail", "exceptions": exc,
                    "sampleSize": int(float(r.get("samplesize") or 0)) if str(r.get("samplesize") or "0").replace(".", "").isdigit() else 0,
                    "description": str(r.get("description") or "")[:500]})
    return out
