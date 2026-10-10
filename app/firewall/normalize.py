"""Firewall layer 1 - canonicalisation.

Attackers hide instructions with invisible characters, look-alike glyphs, spaced-out letters
or full-width forms. Everything is reduced to a canonical form BEFORE detection runs, and the
obfuscation itself is reported as a signal."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

_ZERO_WIDTH = re.compile("[" + "".join(chr(c) for c in (*range(0x200B, 0x2010), *range(0x2060, 0x2065), 0xFEFF, 0x00AD, 0x180E)) + "]")  # built from code points: no raw invisible chars in source
_BIDI = re.compile("[" + "".join(chr(c) for c in (*range(0x202A, 0x202F), *range(0x2066, 0x206A))) + "]")
_TAG_CHARS = re.compile("[\U000e0000-\U000e007f]")
_CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_HOMO = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i", "ѕ": "s", "ј": "j",
    "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w", "ο": "o", "α": "a", "ν": "v", "ι": "i", "κ": "k", "ρ": "p",
    "τ": "t", "υ": "u", "ε": "e", "ɡ": "g", "ı": "i", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M",
    "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "І": "I", "Ѕ": "S",
}
_HOMO_TABLE = {ord(k): v for k, v in _HOMO.items()}
_WORD = re.compile(r"[A-Za-zͰ-ϿЀ-ӿ]{3,}")
_SPACED = re.compile(r"(?<![A-Za-z])(?:[A-Za-z][ \t]{1,3}){5,}[A-Za-z](?![A-Za-z])")
_DOTTED = re.compile(r"(?<![A-Za-z])(?:[A-Za-z][._*\-]){2,}[A-Za-z](?![A-Za-z])")
_LEET = {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i", "|": "i"}
_LEET_TOKEN = re.compile(r"(?<![\w@$!|])[\w@$!|]{3,}(?![\w@$!|])")


@dataclass
class Normalized:
    text: str
    flags: dict = field(default_factory=dict)


def normalize(raw: str) -> Normalized:
    t = "" if raw is None else str(raw)
    flags = {"zeroWidth": 0, "bidi": 0, "tagChars": 0, "homoglyphs": 0, "spaced": 0, "controlChars": 0}

    def count(rx, key, repl=""):
        nonlocal t
        t, n = rx.subn(repl, t)
        flags[key] += n

    count(_TAG_CHARS, "tagChars")
    count(_ZERO_WIDTH, "zeroWidth")
    count(_BIDI, "bidi")
    count(_CONTROL, "controlChars", " ")
    t = unicodedata.normalize("NFKC", t)

    def fold(m: re.Match) -> str:
        w = m.group(0)
        if not re.search(r"[A-Za-z]", w):
            return w  # genuinely non-latin word: leave alone
        out = w.translate(_HOMO_TABLE)
        flags["homoglyphs"] += sum(1 for a, b in zip(w, out) if a != b)
        return out

    t = _WORD.sub(fold, t)

    def despace(m: re.Match) -> str:
        flags["spaced"] += 1
        s = re.sub(r"[ \t]{2,}", "\x00", m.group(0))  # wide gaps = word boundaries
        return re.sub(r"[ \t._*\-]", "", s).replace("\x00", " ")

    t = _SPACED.sub(despace, t)
    t = _DOTTED.sub(despace, t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return Normalized(t, flags)


def leet_fold(text: str, one: str = "i") -> str:
    """`one` resolves the ambiguous '1' / '!' / '|': 'i' (1gnore) or 'l' (a11)."""
    table = {**_LEET, "1": one, "!": one, "|": one}

    def f(m: re.Match) -> str:
        w = m.group(0)
        if not re.search(r"[A-Za-z]", w) or not re.search(r"[0-9@$!|]", w):
            return w
        return "".join(table.get(c, c) for c in w)

    return _LEET_TOKEN.sub(f, text)
