"""Symmetric encryption helpers for storing secrets at rest.

Uses AES-256-GCM with a master key derived from ``MASTER_KEY`` env var.
"""

from __future__ import annotations

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config.settings import get_settings


class CryptoError(RuntimeError):
    """Raised when encryption/decryption fails."""


def _master_key_bytes() -> bytes:
    settings = get_settings()
    if not settings.master_key:
        raise CryptoError("MASTER_KEY is not configured")
    try:
        key = base64.b64decode(settings.master_key)
    except Exception as exc:  # noqa: BLE001
        raise CryptoError("MASTER_KEY is not valid base64") from exc
    if len(key) != 32:
        raise CryptoError("MASTER_KEY must decode to exactly 32 bytes")
    return key


def encrypt_secret(plaintext: str, *, aad: bytes | None = None) -> str:
    """Encrypt and return ``base64(nonce || ciphertext)``."""
    if plaintext == "":
        return ""
    aes = AESGCM(_master_key_bytes())
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt_secret(token: str, *, aad: bytes | None = None) -> str:
    if token == "":
        return ""
    raw = base64.b64decode(token)
    if len(raw) < 13:
        raise CryptoError("ciphertext too short")
    nonce, ct = raw[:12], raw[12:]
    aes = AESGCM(_master_key_bytes())
    return aes.decrypt(nonce, ct, aad).decode("utf-8")
