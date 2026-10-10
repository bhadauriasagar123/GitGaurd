"""Text utilities: tokenisation, TF-IDF cosine, topic taxonomy, quantity extraction."""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an the and or of to in on for with by at from as is are was were be been being that this these those it its
which who whom shall must should may might can could will would not no any all each every such than then there their
they them has have had do does did into over under per via within upon also other more most less only own same so
bank banks entity entities regulated""".split())


def stem(w: str) -> str:
    for suf in ("ations", "ation", "ements", "ement", "utions", "ution", "ings", "ing", "ies", "ied", "ers", "er", "ed", "es", "s", "ly"):
        if w.endswith(suf) and len(w) - len(suf) >= (3 if suf == "s" else 4):
            return w[: -len(suf)] + ("y" if suf in ("ies", "ied") else "")
    return w


def tokens(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z][a-z0-9]{2,}", text.lower()) if w not in STOP]


class TfIdf:
    def __init__(self, docs: list[list[str]]):
        n = len(docs) or 1
        df = Counter(t for d in docs for t in set(d))
        self.idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}

    def vec(self, toks: list[str]) -> dict[str, float]:
        tf = Counter(toks)
        v = {t: (1 + math.log(c)) * self.idf.get(t, 1.0) for t, c in tf.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        return {t: x / norm for t, x in v.items()}

    @staticmethod
    def cosine(a: dict[str, float], b: dict[str, float]) -> float:
        if len(a) > len(b):
            a, b = b, a
        return sum(x * b.get(t, 0.0) for t, x in a.items())


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


# ---------------------------------------------------------------- topic taxonomy
TOPICS: dict[str, list[str]] = {
    "incident-reporting": [r"incident", r"cyber\s+event", r"security\s+event", r"report(?:ing)?\s+(?:to|of)\s+the\s+(?:regulator|authority|reserve)", r"notify\s+the\s+(?:regulator|authority)", r"reportable"],
    "breach-notification": [r"data\s+breach", r"personal\s+data\s+breach", r"breach\s+notif", r"notify\s+(?:affected|data\s+subjects|customers)"],
    "access-control": [r"access\s+control", r"privileged", r"least\s+privilege", r"authenticat", r"multi-?factor", r"\bmfa\b", r"access\s+review", r"user\s+access", r"role-?based", r"authori[sz]ation"],
    "encryption": [r"encrypt", r"cryptograph", r"key\s+management", r"\btls\b", r"\baes\b"],
    "data-retention": [r"retain", r"retention", r"erasure", r"dispos", r"archiv", r"storage\s+limitation", r"record\s+keeping"],
    "logging-monitoring": [r"\blogs?\b", r"logging", r"monitor", r"\bsiem\b", r"audit\s+trail", r"alert"],
    "vendor-risk": [r"third[\s-]part", r"vendor", r"outsourc", r"service\s+provider", r"supplier"],
    "business-continuity": [r"business\s+continuity", r"disaster\s+recovery", r"recovery\s+time", r"\brto\b", r"\brpo\b", r"resilien", r"backup"],
    "vulnerability-mgmt": [r"vulnerab", r"penetration", r"\bpatch", r"security\s+testing", r"red\s+team"],
    "customer-consent": [r"consent", r"opt-?in", r"opt\s*out", r"purpose\s+limitation", r"privacy\s+notice"],
    "kyc-aml": [r"\bkyc\b", r"know\s+your\s+customer", r"money\s+laundering", r"\baml\b", r"suspicious\s+transaction", r"due\s+diligence", r"sanction"],
    "governance": [r"\bboard\b", r"governance", r"senior\s+management", r"risk\s+committee", r"\bciso\b", r"oversight"],
    "training": [r"training", r"awareness", r"competen"],
    "change-management": [r"change\s+management", r"change\s+control", r"release\s+management", r"deployment"],
    "data-subject-rights": [r"data\s+subject", r"right\s+to\s+(?:access|erasure)", r"rectification", r"portability", r"grievance"],
    "capital-liquidity": [r"capital\s+adequacy", r"liquidity", r"leverage\s+ratio", r"\bcar\b"],
    "data-protection": [r"clear[\s-]?text", r"data\s+loss", r"\bdlp\b", r"tokeni[sz]", r"personal\s+devices?", r"removable\s+media", r"\bpins?\b", r"mask(?:ing|ed)"],
    "fraud": [r"fraud", r"unauthori[sz]ed\s+transaction", r"transaction\s+monitoring", r"chargeback", r"dispute"],
}
_TOPIC_RX = {k: re.compile("|".join(v), re.I) for k, v in TOPICS.items()}
TOPIC_WEIGHT = {"incident-reporting": 1.0, "breach-notification": 1.0, "kyc-aml": 1.0, "access-control": 0.8, "encryption": 0.7,
                "capital-liquidity": 1.0, "fraud": 0.8, "data-retention": 0.5, "business-continuity": 0.6, "vendor-risk": 0.5}


def topics_of(text: str) -> list[str]:
    return [k for k, rx in _TOPIC_RX.items() if rx.search(text)]


# ---------------------------------------------------------------- quantities
_NUMW = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty-eight": 48, "forty eight": 48,
         "seventy-two": 72, "seventy two": 72, "twenty-four": 24, "twenty four": 24, "ninety": 90}
_NUM = r"(\d+(?:\.\d+)?|" + "|".join(sorted((re.escape(k) for k in _NUMW), key=len, reverse=True)) + r")"
_UNIT = r"(hours?|hrs?|business\s+days?|working\s+days?|days?|weeks?|months?|years?)"
_HOURS = {"hour": 1, "hr": 1, "day": 24, "week": 168, "month": 730, "year": 8760}


def _num(s: str) -> float:
    s = s.lower()
    return float(_NUMW[s]) if s in _NUMW else float(s)


def to_hours(n: float, unit: str) -> float:
    u = unit.lower()
    for k, v in _HOURS.items():
        if k in u:
            return n * v
    return n


DEADLINE_RX = re.compile(r"\b(?:within|inside|in\s+not\s+more\s+than|not\s+later\s+than|no\s+later\s+than|not\s+more\s+than|up\s+to)\s+" + _NUM + r"\s*" + _UNIT, re.I)
RET_MIN_RX = re.compile(r"\b(?:at\s+least|not\s+less\s+than|minimum\s+(?:of|period\s+of)|for\s+a\s+minimum\s+of)\s+" + _NUM + r"\s*" + _UNIT, re.I)
RET_MAX_RX = re.compile(r"\b(?:no\s+longer\s+than|not\s+(?:be\s+)?(?:retained|kept|stored)\s+(?:for\s+)?(?:longer|more)\s+than|not\s+exceed(?:ing)?|maximum\s+(?:of|period\s+of)|for\s+no\s+more\s+than)\s+" + _NUM + r"\s*" + _UNIT, re.I)
FREQ_RX = re.compile(r"\b(daily|weekly|monthly|quarterly|half[\s-]yearly|semi[\s-]?annual(?:ly)?|annual(?:ly)?|yearly|continuous(?:ly)?|real[\s-]time)\b", re.I)
FREQ_DAYS = {"daily": 1, "continuous": 0.04, "continuously": 0.04, "real-time": 0.04, "real time": 0.04, "weekly": 7, "monthly": 31,
             "quarterly": 92, "half-yearly": 184, "half yearly": 184, "semi-annual": 184, "semiannual": 184, "semi-annually": 184,
             "semiannually": 184, "annual": 366, "annually": 366, "yearly": 366}


def frequency_days(text: str) -> float | None:
    m = FREQ_RX.search(text)
    if m:
        return FREQ_DAYS.get(re.sub(r"\s+", "-", m.group(1).lower()), FREQ_DAYS.get(m.group(1).lower()))
    m = re.search(r"\b(?:every|each|per)\s+(day|week|month|quarter|year)\b", text, re.I)
    if m:
        return {"day": 1, "week": 7, "month": 31, "quarter": 92, "year": 366}[m.group(1).lower()]
    m = re.search(r"\bevery\s+" + _NUM + r"\s*(days?|weeks?|months?|years?)", text, re.I)
    if m:
        return to_hours(_num(m.group(1)), m.group(2)) / 24
    return None


def deadline_hours(text: str) -> float | None:
    m = DEADLINE_RX.search(text)
    return to_hours(_num(m.group(1)), m.group(2)) if m else None


def retention(text: str) -> dict:
    out = {}
    m = RET_MIN_RX.search(text)
    if m:
        out["minHours"] = to_hours(_num(m.group(1)), m.group(2))
    m = RET_MAX_RX.search(text)
    if m:
        out["maxHours"] = to_hours(_num(m.group(1)), m.group(2))
    return out


def humanize_hours(h: float | None) -> str | None:
    if h is None:
        return None
    if h >= 8760 and h % 8760 == 0:
        return f"{int(h // 8760)} year(s)"
    if h >= 730 and abs(h / 730 - round(h / 730)) < 0.01:
        return f"{round(h / 730)} month(s)"
    if h >= 96 and h % 24 == 0:
        return f"{int(h // 24)} day(s)"
    return f"{h:g} hour(s)"
