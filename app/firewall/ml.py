"""Learned intent classifier (second opinion next to the deterministic rules).

Pure-Python inference (no numpy/sklearn at runtime): hashed word + char n-gram features -> softmax regression with
10 classes (9 attack classes + benign). Weights are trained offline by scripts/train_firewall_model.py and shipped
as app/firewall/model.json. Why: hand-written rules measured only ~22% recall on unseen phrasings and languages;
a statistical model generalises across paraphrase and language, while the rules stay as precise, explainable evidence."""
from __future__ import annotations

import json
import math
import re
import zlib
from functools import lru_cache
from pathlib import Path

DIM = 1 << 16
MODEL_PATH = Path(__file__).with_name("model.json")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def features(text: str) -> dict[int, float]:
    """Hashed bag of word unigrams/bigrams and char 3-5-grams (inside words). L2-normalised."""
    words = _WORD.findall(text.lower())[:120]
    feats: dict[int, float] = {}

    def add(s: str, w: float = 1.0):
        i = zlib.crc32(s.encode("utf8")) & (DIM - 1)
        feats[i] = feats.get(i, 0.0) + w

    for k, w in enumerate(words):
        add("w:" + w)
        if k:
            add("b:" + words[k - 1] + "_" + w)
        p = f"<{w}>"
        for n in (3, 4, 5):
            for j in range(0, max(0, len(p) - n + 1)):
                add("c:" + p[j:j + n], 0.5)
    norm = math.sqrt(sum(v * v for v in feats.values())) or 1.0
    return {i: v / norm for i, v in feats.items()}


class IntentModel:
    def __init__(self, classes: list[str], bias: list[float], weights: list[dict[int, float]]):
        self.classes, self.bias, self.weights = classes, bias, weights

    def predict(self, text: str) -> tuple[str, float, dict[str, float]]:
        """Return (best attack class or 'BENIGN', P(attack), per-class probabilities)."""
        f = features(text)
        if not f:
            return "BENIGN", 0.0, {}
        z = [b + sum(w.get(i, 0.0) * v for i, v in f.items()) for b, w in zip(self.bias, self.weights)]
        m = max(z)
        e = [math.exp(x - m) for x in z]
        s = sum(e)
        p = {c: x / s for c, x in zip(self.classes, e)}
        p_attack = 1.0 - p.get("BENIGN", 0.0)
        best = max((c for c in self.classes if c != "BENIGN"), key=lambda c: p[c])
        return (best if p_attack >= 0.5 else "BENIGN"), p_attack, p


@lru_cache(maxsize=1)
def load_model() -> IntentModel | None:
    if not MODEL_PATH.exists():
        return None
    d = json.loads(MODEL_PATH.read_text(encoding="utf8"))
    return IntentModel(d["classes"], d["bias"], [{int(k): v for k, v in w.items()} for w in d["weights"]])


_SENT = re.compile(r"(?<=[.!?;])\s+|\n+")  # ':' deliberately not a boundary: "Act as a reviewer: who owns C-04?" is one thought


def sentences(text: str, limit: int = 1500) -> list[tuple[int, int, str]]:
    """(start, end, text) for each sentence-like unit, linear time."""
    out, pos = [], 0
    for m in _SENT.finditer(text):
        if m.start() > pos:
            out.append((pos, m.start(), text[pos:m.start()]))
        pos = m.end()
        if len(out) >= limit:
            return out
    if pos < len(text):
        out.append((pos, len(text), text[pos:]))
    return out
