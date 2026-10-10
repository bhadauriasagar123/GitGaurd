"""Firewall layer 0 - source adapters (Strategy pattern).

Each input source (user message, web/HTML, PDF, e-mail, Markdown, Word, API JSON, OCR text,
source code, image-OCR) has its own extractor that splits content into *segments* tagged by
channel: visible | hidden | comment | metadata. Hidden channels (CSS-hidden text, comments, alt
text, document metadata, w:vanish runs...) are the classic carriers of indirect injection."""
from __future__ import annotations

import base64
import html as htmllib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import Callable

MAX_NODES = 5000
UNTRUSTED_SOURCES = {"web", "html", "pdf", "email", "markdown", "docx", "api", "ocr", "code", "image"}
SOURCE_TYPES = ["user", "web", "html", "pdf", "email", "markdown", "docx", "api", "ocr", "code", "image", "text"]


@dataclass
class Segment:
    text: str
    channel: str = "visible"  # visible | hidden | comment | metadata
    path: str = ""


# ------------------------------------------------------------------ HTML
_TAG = re.compile(r"<([a-zA-Z][a-zA-Z0-9]*)\b([^<>]*)>")
_HIDDEN_STYLE = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0|opacity\s*:\s*0(?:\.0+)?\b|"
    r"color\s*:\s*(?:#fff(?:fff)?\b|white\b)|text-indent\s*:\s*-\d{3,}|height\s*:\s*0|width\s*:\s*0|left\s*:\s*-\d{3,}px",
    re.I,
)
_HIDDEN_ATTR = re.compile(r"\bhidden\b|aria-hidden\s*=\s*[\"']?true", re.I)
_ATTR_TEXT = re.compile(r"\b(alt|title|aria-label|placeholder|content|data-[\w-]+)\s*=\s*(\"[^\"]{1,2000}\"|'[^']{1,2000}')", re.I)
_VOID = {"br", "img", "meta", "input", "hr", "link"}


def _strip_tags(s: str) -> str:
    for name in ("script", "style"):
        s = _strip_spans(s, _delimited(s, f"<{name}", f"</{name}", cap=10**9, ci=True))
    s = re.sub(r"<[^<>]{0,2000}>", " ", s)
    return htmllib.unescape(re.sub(r"\s+", " ", s)).strip()


_ASCII_LOWER = {c: c + 32 for c in range(65, 91)}


def _lower(s: str) -> str:
    """Length-preserving lower-casing (str.lower() can change length, which would misalign spans)."""
    return s.translate(_ASCII_LOWER)


def _delimited(text: str, opener: str, closer: str, cap: int = 20000, ci: bool = False) -> list[tuple[int, int, str]]:
    """Linear-time opener..closer scanner (str.find only). Regexes such as `<!--(.*?)-->` are quadratic on
    inputs like '<!--' * 50000 (measured: 146 s for 200 KB) - a trivial DoS - so they are never used here.
    An unterminated tail is taken up to `cap` characters."""
    hay = _lower(text) if ci else text
    out, i = [], 0
    while True:
        s = hay.find(opener, i)
        if s == -1:
            return out
        b = s + len(opener)
        e = hay.find(closer, b)
        if e == -1:
            out.append((s, min(len(text), b + cap), text[b:b + cap]))
            return out
        out.append((s, e + len(closer), text[b:e][:cap]))
        i = e + len(closer)


def _strip_spans(text: str, spans: list[tuple[int, int, str]]) -> str:
    out, pos = [], 0
    for s, e, _ in spans:
        out.append(text[pos:s])
        out.append(" ")
        pos = e
    out.append(text[pos:])
    return "".join(out)


def extract_html(content: str) -> list[Segment]:
    segs: list[Segment] = []
    comments = _delimited(content, "<!--", "-->")
    for _, _, body in comments:
        segs.append(Segment(body.strip(), "comment", "html-comment"))
    for name in ("script", "noscript", "style"):
        for _, _, body in _delimited(content, f"<{name}", f"</{name}", ci=True):
            body = body.partition(">")[2].strip()  # drop the rest of the opening tag
            if body and name != "style":
                segs.append(Segment(body, "hidden", f"<{name}>"))
    rest = _strip_spans(content, comments)
    removed: list[tuple[int, int]] = []
    lower = _lower(rest)
    for m in _TAG.finditer(rest):
        tag, attrs = m.group(1).lower(), m.group(2)
        for am in _ATTR_TEXT.finditer(attrs):
            val = am.group(2)[1:-1].strip()
            if len(val) >= 12 and not val.startswith(("http", "#", "/")):
                segs.append(Segment(htmllib.unescape(val), "hidden", f"{tag}@{am.group(1).lower()}"))
        if tag in _VOID or not (_HIDDEN_STYLE.search(attrs) or _HIDDEN_ATTR.search(attrs)):
            continue
        close = lower.find(f"</{tag}", m.end())
        if close == -1:
            continue
        inner = _strip_tags(rest[m.end():close])
        if inner:
            segs.append(Segment(inner, "hidden", f"<{tag}> hidden by CSS/attr"))
            removed.append((m.start(), close))
    visible = rest
    for s, e in sorted(removed, reverse=True):
        visible = visible[:s] + " " + visible[e:]
    segs.insert(0, Segment(_strip_tags(visible), "visible", "body"))
    return segs


# ------------------------------------------------------------------ Markdown
def extract_markdown(content: str) -> list[Segment]:
    segs: list[Segment] = []
    comments = _delimited(content, "<!--", "-->")
    for _, _, c in comments:
        segs.append(Segment(c.strip(), "comment", "md-comment"))
    body = _strip_spans(content, comments)
    for m in re.finditer(r"^\[([^\]]{1,80})\]:\s*\S+\s+[\"'(]([^\"')]{8,500})[\"')]", body, re.M):
        segs.append(Segment(m.group(2), "hidden", "md-ref-title"))
    for m in re.finditer(r"^\[//\]:\s*#\s*\(([^)]{1,2000})\)", body, re.M):
        segs.append(Segment(m.group(1), "comment", "md-hidden-comment"))
    for m in re.finditer(r"!?\[[^\]]{0,200}\]\(\s*\S{1,500}\s+\"([^\"]{8,500})\"\s*\)", body):
        segs.append(Segment(m.group(1), "hidden", "md-link-title"))
    if re.search(r"<(?:img|div|span|p|a)\b", body, re.I):  # inline html
        segs.extend(extract_html(body))
        return segs
    segs.insert(0, Segment(body, "visible", "body"))
    return segs


# ------------------------------------------------------------------ e-mail
def extract_email(content: str) -> list[Segment]:
    head, _, body = content.partition("\n\n")
    if not re.match(r"^(?:from|to|subject|date|reply-to|cc|bcc|received|message-id|mime-version|content-type|x-[\w-]+)\s*:", head, re.I):
        head, body = "", content
    segs: list[Segment] = []
    for line in head.splitlines():
        k, _, v = line.partition(":")
        if k.strip().lower() in ("subject", "reply-to", "from", "x-priority", "comments", "keywords", "x-ai-note"):
            segs.append(Segment(v.strip(), "metadata", f"header:{k.strip().lower()}"))
    if re.search(r"<(?:html|div|p|span|body|a|img)\b", body, re.I):
        segs.extend(extract_html(body))
    else:
        segs.append(Segment(body, "visible", "body"))
    return segs


# ------------------------------------------------------------------ code
def extract_code(content: str) -> list[Segment]:
    segs = [Segment(content, "visible", "code")]
    for m in re.finditer(r"(?://|#|--)\s?(.{4,500})$", content, re.M):
        segs.append(Segment(m.group(1), "comment", "line-comment"))
    for _, _, c in _delimited(content, "/*", "*/", 5000):
        segs.append(Segment(c, "comment", "block-comment"))
    for q in ('"""', "'''"):
        for _, _, c in _delimited(content, q, q, 5000):
            segs.append(Segment(c, "comment", "docstring"))
    return segs


# ------------------------------------------------------------------ API JSON
def extract_api(content: str) -> list[Segment]:
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):
        return [Segment(content, "visible", "raw")]
    segs: list[Segment] = []
    budget = [MAX_NODES]

    def walk(node, path, depth):
        if budget[0] <= 0 or depth > 12:
            return
        budget[0] -= 1
        if isinstance(node, str):
            segs.append(Segment(node, "visible", path or "$"))
        elif isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str) and len(k) > 40:  # long keys are suspicious carriers
                    segs.append(Segment(k, "metadata", f"{path}.<key>"))
                walk(v, f"{path}.{k}", depth + 1)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]", depth + 1)

    walk(data, "$", 0)
    segs.append(Segment(content[:200_000], "metadata", "raw-json"))  # key:value structure (e.g. {"tool":"send_email"}) is itself a carrier
    return segs


# ------------------------------------------------------------------ DOCX / PDF (binary -> text)
def extract_docx_bytes(raw: bytes) -> list[Segment]:
    """Minimal OOXML reader with zip-bomb guards; surfaces w:vanish (hidden) runs and comments."""
    segs: list[Segment] = []
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        total = sum(i.file_size for i in z.infolist())
        if total > 30_000_000 or len(z.infolist()) > 500:
            raise ValueError("docx archive too large (possible zip bomb)")
        for name, channel in (("word/document.xml", "visible"), ("word/comments.xml", "comment"),
                              ("word/footnotes.xml", "hidden"), ("docProps/core.xml", "metadata"),
                              ("docProps/custom.xml", "metadata")):
            if name not in z.namelist():
                continue
            xml = z.read(name).decode("utf8", "ignore")
            if name == "word/document.xml":
                vis, hid = [], []
                runs = [r for _, _, r in _delimited(xml, "<w:r>", "</w:r>")] + [r for _, _, r in _delimited(xml, "<w:r ", "</w:r>")]
                for run in runs:
                    text = "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", run))
                    if not text:
                        continue
                    tiny = re.search(r'<w:sz w:val="([0-9]+)"', run)
                    white = re.search(r'<w:color w:val="(?:FFFFFF|ffffff)"', run)
                    if "<w:vanish" in run or white or (tiny and int(tiny.group(1)) <= 2):
                        hid.append(text)
                    else:
                        vis.append(text)
                segs.append(Segment(htmllib.unescape(" ".join(vis)), "visible", name))
                if hid:
                    segs.append(Segment(htmllib.unescape(" ".join(hid)), "hidden", "w:vanish/white/tiny runs"))
            else:
                text = htmllib.unescape(" ".join(re.findall(r">([^<>]{3,})<", xml)))
                if text.strip():
                    segs.append(Segment(text, channel, name))
    return segs


def extract_pdf_bytes(raw: bytes) -> list[Segment]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    if len(reader.pages) > 200:
        raise ValueError("pdf too long")
    segs = [Segment("\n".join((p.extract_text() or "") for p in reader.pages), "visible", "pdf-text")]
    meta = reader.metadata or {}
    for k, v in meta.items():
        if isinstance(v, str) and v.strip():
            segs.append(Segment(v, "metadata", f"pdf-meta:{k}"))
    for i, p in enumerate(reader.pages):
        for a in (p.get("/Annots") or []):
            try:
                c = a.get_object().get("/Contents")
                if c:
                    segs.append(Segment(str(c), "hidden", f"pdf-annot p{i + 1}"))
            except Exception:
                continue
    return segs


# ------------------------------------------------------------------ registry
Extractor = Callable[[str], list[Segment]]
EXTRACTORS: dict[str, Extractor] = {
    "web": extract_html, "html": extract_html, "markdown": extract_markdown, "email": extract_email,
    "code": extract_code, "api": extract_api,
}


def extract(source_type: str, content: str | None, content_b64: str | None, metadata: dict | None) -> list[Segment]:
    if content_b64:
        raw = base64.b64decode(content_b64, validate=True)
        try:
            if source_type == "docx":
                segs = extract_docx_bytes(raw)
            elif source_type == "pdf":
                segs = extract_pdf_bytes(raw)
            else:
                segs = [Segment(raw.decode("utf8", "ignore"), "visible", "raw")]
        except ValueError:
            raise
        except Exception as e:  # BadZipFile, pypdf errors, ... -> uniform "unparseable" signal (never a 500)
            raise ValueError(f"unparseable {source_type}: {type(e).__name__}") from None
    else:
        fn = EXTRACTORS.get(source_type)
        segs = fn(content or "") if fn else [Segment(content or "", "visible", "body")]
    for k, v in (metadata or {}).items():
        if isinstance(v, str) and v.strip():
            segs.append(Segment(v, "metadata", f"meta:{str(k)[:40]}"))
    return segs
