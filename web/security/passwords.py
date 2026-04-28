"""Password hashing using bcrypt + per-deployment pepper."""

from __future__ import annotations

import bcrypt

from config.settings import get_settings

_BCRYPT_ROUNDS = 12


def _peppered(password: str) -> bytes:
    settings = get_settings()
    return (password + settings.auth_pepper).encode("utf-8")


def hash_password(password: str) -> str:
    if len(password) < 8 or len(password) > 128:
        raise ValueError("password length must be between 8 and 128")
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(_peppered(password), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_peppered(password), hashed.encode("utf-8"))
    except ValueError:
        return False
