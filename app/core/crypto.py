"""AES-256-GCM envelope encryption for documents at rest + helpers for hashing/ids."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings


def _aes() -> AESGCM:
    return AESGCM(get_settings().enc_key_bytes())


def encrypt(plaintext: str, aad: str = "") -> dict:
    """Authenticated encryption: the AAD (tenant:docId) binds ciphertext to its owner, so a
    ciphertext copied across tenants or records fails to decrypt."""
    iv = os.urandom(12)
    ct = _aes().encrypt(iv, plaintext.encode("utf-8"), aad.encode())
    return {"iv": base64.b64encode(iv).decode(), "ct": base64.b64encode(ct).decode(), "alg": "AES-256-GCM"}


def decrypt(box: dict, aad: str = "") -> str:
    return _aes().decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["ct"]), aad.encode()).decode("utf-8")


def sha256(data: str | bytes) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def hmac_hex(data: str) -> str:
    return hmac.new(get_settings().enc_key_bytes(), data.encode(), hashlib.sha256).hexdigest()


def safe_equal(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"
