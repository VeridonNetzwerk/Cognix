"""Tests for security: tokens, passwords, crypto."""

from __future__ import annotations

import base64
import secrets
import time
import pytest

from web.security.tokens import (
    TokenError,
    decode_token,
    hash_refresh_token,
    issue_access_token,
    issue_refresh_token,
)
from web.security.passwords import hash_password, verify_password
from bot.config.crypto import CryptoError, decrypt_secret, encrypt_secret


class TestTokens:
    """JWT token issue/verify."""

    def test_issue_and_decode_access_token(self):
        token = issue_access_token(subject="user-123", role="ADMIN")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "user-123"
        assert payload["role"] == "ADMIN"
        assert payload["typ"] == "access"

    def test_issue_and_decode_refresh_token(self):
        import uuid
        family_id = uuid.uuid4()
        token, exp = issue_refresh_token(subject="user-123", family_id=family_id)
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "user-123"
        assert payload["typ"] == "refresh"
        assert payload["fam"] == family_id.hex

    def test_decode_wrong_type(self):
        token = issue_access_token(subject="user-123", role="ADMIN")
        with pytest.raises(TokenError, match="unexpected token type"):
            decode_token(token, expected_type="refresh")

    def test_decode_invalid_token(self):
        with pytest.raises(TokenError):
            decode_token("invalid.jwt.token", expected_type="access")

    def test_access_token_has_jti(self):
        token = issue_access_token(subject="user-123", role="ADMIN")
        payload = decode_token(token, expected_type="access")
        assert "jti" in payload
        assert len(payload["jti"]) == 32  # uuid4 hex

    def test_remember_me_extends_ttl(self):
        import uuid
        token_normal, exp_normal = issue_refresh_token(
            subject="user-123", family_id=uuid.uuid4()
        )
        token_remember, exp_remember = issue_refresh_token(
            subject="user-123", family_id=uuid.uuid4(), remember_me=True
        )
        # Remember-me token should expire later
        assert exp_remember > exp_normal

    def test_hash_refresh_token_deterministic(self):
        token = "test-token-123"
        h1 = hash_refresh_token(token)
        h2 = hash_refresh_token(token)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_hash_refresh_token_different_inputs(self):
        assert hash_refresh_token("token1") != hash_refresh_token("token2")


class TestPasswords:
    """Password hashing and verification."""

    def test_hash_and_verify(self):
        pw = "my-secret-password"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_different_passwords_different_hashes(self):
        h1 = hash_password("password1")
        h2 = hash_password("password2")
        assert h1 != h2

    def test_hash_same_password_different_hashes(self):
        """Bcrypt salt should make each hash unique."""
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        assert h1 != h2

    def test_verify_empty_hash(self):
        assert verify_password("anything", "") is False

    def test_hash_too_short(self):
        with pytest.raises(ValueError, match="password length"):
            hash_password("short")

    def test_hash_too_long(self):
        with pytest.raises(ValueError, match="password length"):
            hash_password("x" * 129)


class TestCrypto:
    """AES-GCM encrypt/decrypt."""

    def test_encrypt_and_decrypt(self):
        plaintext = "my-secret-data"
        encrypted = encrypt_secret(plaintext)
        assert encrypted != plaintext
        assert decrypt_secret(encrypted) == plaintext

    def test_encrypt_empty_string(self):
        assert encrypt_secret("") == ""
        assert decrypt_secret("") == ""

    def test_encrypt_with_aad(self):
        plaintext = "secret"
        encrypted = encrypt_secret(plaintext, aad=b"bot_token")
        assert decrypt_secret(encrypted, aad=b"bot_token") == plaintext

    def test_decrypt_wrong_aad(self):
        plaintext = "secret"
        encrypted = encrypt_secret(plaintext, aad=b"bot_token")
        with pytest.raises(CryptoError):
            decrypt_secret(encrypted, aad=b"wrong_aad")

    def test_encrypt_different_each_time(self):
        plaintext = "same-secret"
        e1 = encrypt_secret(plaintext)
        e2 = encrypt_secret(plaintext)
        assert e1 != e2  # random nonce

    def test_decrypt_tampered(self):
        plaintext = "secret"
        encrypted = encrypt_secret(plaintext)
        # Tamper with the encrypted data
        tampered = encrypted[:-4] + "AAAA"
        with pytest.raises(CryptoError):
            decrypt_secret(tampered)
