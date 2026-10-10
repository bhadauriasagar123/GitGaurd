"""Firewall layer 2 - decoders (Strategy pattern, applied recursively).

Encoded instructions (base64, hex, URL-encoding, unicode escapes, HTML entities, ROT13,
reversed text) are decoded into *variants* that are scanned exactly like plain text."""
from __future__ import annotations

import base64
import binascii
import codecs
import html
import re
import urllib.parse
from dataclasses import dataclass

MAX_VARIANTS = 40
MAX_DEPTH = 3


@dataclass
class Variant:
    text: str
    chain: tuple[str, ...]
    span: tuple[int, int] | None  # span in the ROOT text that carried the encoding (None = whole segment)


def _printable(s: str) -> bool:
    return bool(s) and len(s) >= 8 and sum(c.isprintable() or c in "\n\t" for c in s) / len(s) >= 0.92


def _b64(text: str):
    for m in re.finditer(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{24,}={0,2}(?![A-Za-z0-9+/])", text):
        blob = m.group(0)
        try:
            dec = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
        if _printable(dec):
            yield dec, m.span()


def _hex(text: str):
    for m in re.finditer(r"(?:\b(?:0x)?[0-9a-fA-F]{2}\b[ :,]?){12,}", text):
        cleaned = re.sub(r"0x|[ :,]", "", m.group(0))
        if len(cleaned) % 2:
            continue
        try:
            dec = bytes.fromhex(cleaned).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if _printable(dec):
            yield dec, m.span()
    for m in re.finditer(r"\b[0-9a-fA-F]{24,}\b", text):
        if len(m.group(0)) % 2:
            continue
        try:
            dec = bytes.fromhex(m.group(0)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if _printable(dec):
            yield dec, m.span()


def _url(text: str):
    if len(re.findall(r"%[0-9a-fA-F]{2}", text)) >= 4:
        dec = urllib.parse.unquote(text)
        if dec != text:
            yield dec, None


def _uesc(text: str):
    if len(re.findall(r"\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}", text)) >= 4:
        try:
            dec = codecs.decode(text.encode("latin1", "ignore"), "unicode_escape")
        except Exception:
            return
        if dec != text:
            yield dec, None


def _entities(text: str):
    if len(re.findall(r"&#x?[0-9a-fA-F]+;", text)) >= 4:
        dec = html.unescape(text)
        if dec != text:
            yield dec, None


def _rot13(text: str):
    if len(text) <= 20000:
        yield codecs.encode(text, "rot13"), None


def _reverse(text: str):
    if len(text) <= 20000:
        yield text[::-1], None


def _binary(text: str):
    for m in re.finditer(r"(?:\b[01]{8}\b[ ]?){8,}", text):
        bits = re.sub(r"\s", "", m.group(0))
        try:
            dec = bytes(int(bits[i:i + 8], 2) for i in range(0, len(bits), 8)).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            continue
        if _printable(dec):
            yield dec, m.span()


DECODERS = {"base64": _b64, "hex": _hex, "url": _url, "unicode-escape": _uesc, "html-entity": _entities,
            "binary": _binary, "rot13": _rot13, "reversed": _reverse}
# whole-text transforms only make sense at depth 0 (otherwise combinatorial noise)
_TRANSFORMS = {"rot13", "reversed"}


def decode_variants(text: str) -> list[Variant]:
    out: list[Variant] = []
    seen = {text}

    def rec(cur: str, chain: tuple[str, ...], root_span, depth: int):
        if depth >= MAX_DEPTH or len(out) >= MAX_VARIANTS:
            return
        for name, fn in DECODERS.items():
            if name in _TRANSFORMS and depth > 0 and name not in ("rot13",):
                continue
            if name == "rot13" and depth > 0 and chain and chain[-1] == "rot13":
                continue
            for dec, span in fn(cur):
                if dec in seen or len(out) >= MAX_VARIANTS:
                    continue
                seen.add(dec)
                v = Variant(dec, chain + (name,), root_span if root_span else span)
                out.append(v)
                if name not in _TRANSFORMS:
                    rec(dec, v.chain, v.span, depth + 1)

    rec(text, (), None, 0)
    return out
