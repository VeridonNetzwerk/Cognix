"""TOTP (RFC 6238) helpers."""

from __future__ import annotations

import io
import secrets
from base64 import b64encode

import pyotp

try:
    import qrcode  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    qrcode = None  # type: ignore[assignment]

from config.crypto import decrypt_secret, encrypt_secret


def generate_secret() -> str:
    return pyotp.random_base32(length=32)


def encrypted_secret(secret: str) -> str:
    return encrypt_secret(secret, aad=b"totp")


def decrypt(secret_enc: str) -> str:
    return decrypt_secret(secret_enc, aad=b"totp")


def provisioning_uri(secret: str, *, account: str, issuer: str = "CogniX") -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def qr_data_url(uri: str) -> str:
    if qrcode is None:
        raise RuntimeError("qrcode package is not installed; install 'qrcode[pil]' to enable TOTP QR generation")
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + b64encode(buf.getvalue()).decode("ascii")


def verify(secret: str, code: str) -> bool:
    if not secret or not code:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, valid_window=1)
    except Exception:  # noqa: BLE001
        return False


def generate_backup_codes(n: int = 8) -> list[str]:
    return [secrets.token_hex(5).upper() for _ in range(n)]
