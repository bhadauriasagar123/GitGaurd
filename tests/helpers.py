"""Builders for compact, readable scenario tests."""
from __future__ import annotations

import io
import json
import zipfile
from datetime import date, timedelta

from app.compliance.controls import parse_controls, parse_evidence

TODAY = date.today()


def d(days_ago: int) -> str:
    return (TODAY - timedelta(days=days_ago)).isoformat()


def reg(code="R1", version="1.0", text="", jur="IN", eff=None, entity=None):
    return {"meta": {"code": code, "version": version, "jurisdiction": jur, "effectiveDate": eff or d(400), "entityTypes": entity or ["all"]}, "text": text}


def ctrl_text(*controls: dict) -> str:
    out = []
    for c in controls:
        out.append("\n".join(f"{k.title()}: {v}" for k, v in {"control id": c["id"], "title": c.get("title", c["id"]), "description": c["description"],
                                                            "owner": c.get("owner", "Owner X"), "type": c.get("type", "preventive"),
                                                            "frequency": c.get("frequency", "continuous"), "automation": c.get("automation", "automated")}.items()))
    return "\n\n".join(out)


def mk_state(regs, controls=(), evidence=(), profile=None):
    ev = [{"id": f"E{i}", "control": c, "date": dt, "result": r, "exceptions": x} for i, (c, dt, r, x) in enumerate(evidence)]
    return {"profile": profile or {"entityType": "scheduled commercial bank", "jurisdictions": ["IN", "EU"]},
            "regulations": list(regs), "controls": parse_controls(ctrl_text(*controls)) if controls else [],
            "evidence": parse_evidence(json.dumps(ev)) if ev else []}


# ---- minimal real file builders for binary-source scenarios
def make_docx(visible: str, hidden: str | None = None, comment: str | None = None) -> bytes:
    run = lambda t, rpr="": f"<w:r>{('<w:rPr>' + rpr + '</w:rPr>') if rpr else ''}<w:t>{t}</w:t></w:r>"
    body = run(visible) + (run(hidden, "<w:vanish/>") if hidden else "")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", f"<w:document><w:body><w:p>{body}</w:p></w:body></w:document>")
        if comment:
            z.writestr("word/comments.xml", f"<w:comments><w:comment><w:p><w:r><w:t>{comment}</w:t></w:r></w:p></w:comment></w:comments>")
    return buf.getvalue()


def make_pdf(text: str, subject: str | None = None) -> bytes:
    """Smallest valid single-page PDF with one line of text (+ optional /Subject metadata)."""
    esc = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 11 Tf 40 760 Td ({esc}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    info = None
    if subject:
        objs.append(b"<< /Subject (" + subject.replace("(", "").replace(")", "").encode() + b") >>")
        info = len(objs)
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    x = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for o in offs:
        out += f"{o:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R{f' /Info {info} 0 R' if info else ''} >>\nstartxref\n{x}\n%%EOF".encode()
    return bytes(out)
