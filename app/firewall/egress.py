"""Egress guard (output firewall) + Prompt Vault.

This is what guarantees that nobody can extract the agent's prompt or the customer's
confidential documents through the model: every LLM output (and every outbound assistant
message) is inspected for canary tokens, system-prompt fragments, bulk verbatim document
leakage, secret material and URL-based exfiltration channels - and redacted before release."""
from __future__ import annotations

import hashlib
import re
import threading

from app.core import crypto

SECRET_PATTERNS = [
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("api-secret", re.compile(r"\bsk-[A-Za-z0-9_\-]{20,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("azure-key", re.compile(r"(?i)\b(?:AccountKey|SharedAccessKey|api-key)\s*[=:]\s*[A-Za-z0-9+/=]{20,}")),
    ("conn-string", re.compile(r"(?i)\b(?:postgres(?:ql)?|redis|rediss|mongodb)://[^\s:@]+:[^\s@]+@")),
]
EXFIL_URL = re.compile(r"(?:!\[[^\]]{0,80}\]\(|<img[^>]{0,100}src=[\"']?)(https?://[^)\s\"'>]{0,300}\?[^)\s\"'>]{0,300})", re.I)
_WORD = re.compile(r"[a-z0-9']+")
SHINGLE = 8
ALLOWED_QUOTE_WORDS = 30


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _shingles(words: list[str]) -> list[str]:
    return [hashlib.blake2b(" ".join(words[i:i + SHINGLE]).encode(), digest_size=8).hexdigest()
            for i in range(0, max(0, len(words) - SHINGLE + 1))]


class PromptVault:
    """Holds fingerprints (never plaintext copies exposed via API) of protected prompts and
    plants a per-prompt canary token. If the canary or prompt shingles ever show up in an
    output, the egress guard blocks the response."""

    def __init__(self):
        self._lock = threading.Lock()
        self._prompts: dict[str, dict] = {}

    def register(self, name: str, prompt: str) -> str:
        canary = "CNRY-" + crypto.hmac_hex("canary:" + name)[:14]
        with self._lock:
            self._prompts[name] = {"canary": canary, "shingles": set(_shingles(_words(prompt))), "sha": crypto.sha256(prompt)[:16]}
        return canary

    def canaries(self) -> list[str]:
        return [p["canary"] for p in self._prompts.values()]

    def shingle_sets(self) -> list[tuple[str, set]]:
        return [(n, p["shingles"]) for n, p in self._prompts.items()]

    def status(self) -> list[dict]:
        return [{"name": n, "fingerprint": p["sha"], "shingles": len(p["shingles"])} for n, p in self._prompts.items()]


vault = PromptVault()


def inspect(text: str, protected_docs: list[str] | None = None) -> dict:
    """Return {allowed, text, findings}. `text` is the redacted release candidate."""
    findings: list[dict] = []
    out = text or ""

    for c in vault.canaries():
        if c in out:
            findings.append({"type": "canary-token", "severity": "critical", "detail": "system prompt canary present in output"})
            out = out.replace(c, "[REDACTED:CANARY]")

    for name, rx in SECRET_PATTERNS:
        if rx.search(out):
            findings.append({"type": "secret", "severity": "critical", "detail": name})
            out = rx.sub("[REDACTED:SECRET]", out)

    if EXFIL_URL.search(out):
        findings.append({"type": "exfil-url", "severity": "high", "detail": "image/URL with query payload (data exfiltration channel)"})
        out = EXFIL_URL.sub("[REDACTED:EXFIL-URL]", out)

    words = _words(out)
    sh = _shingles(words)
    if sh:
        sources = [("system-prompt:" + n, s) for n, s in vault.shingle_sets()]
        for i, d in enumerate(protected_docs or []):
            sources.append((f"document:{i}", set(_shingles(_words(d)))))
        for name, sset in sources:
            matched = [i for i, h in enumerate(sh) if h in sset]
            if not matched:
                continue
            covered = set()
            for i in matched:
                covered.update(range(i, i + SHINGLE))
            is_prompt = name.startswith("system-prompt")
            if is_prompt or len(covered) > ALLOWED_QUOTE_WORDS:
                findings.append({"type": "verbatim-leak", "severity": "critical" if is_prompt else "high",
                                 "detail": f"{len(covered)} words overlap with protected {name.split(':')[0]}"})
                # redact the overlapped words
                toks = list(re.finditer(r"[A-Za-z0-9']+", out))
                spans = [toks[w].span() for w in sorted(covered) if w < len(toks)]
                for s, e in reversed(spans):
                    out = out[:s] + "▮" * min(e - s, 3) + out[e:]
                out = re.sub(r"▮+(?:\W{0,3}▮+)+", "[REDACTED:PROTECTED-CONTENT]", out)

    blocked = any(f["severity"] == "critical" for f in findings)
    return {"allowed": not blocked, "text": out if not blocked else "[Response withheld by egress firewall: protected content detected]",
            "redactedText": out, "findings": findings}
