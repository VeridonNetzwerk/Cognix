"""Tests for web.security.passwords — bcrypt hashing with pepper."""

from __future__ import annotations

import pytest

from web.security.passwords import hash_password, verify_password


class TestHashPassword:
    """Tests for hash_password()."""

    def test_hash_returns_string(self):
        h = hash_password("testPassword123")
        assert isinstance(h, str)
        assert h != "testPassword123"

    def test_hash_is_bcrypt_format(self):
        h = hash_password("testPassword123")
        assert h.startswith("$2b$")

    def test_hash_too_short_raises(self):
        with pytest.raises(ValueError, match="password length"):
            hash_password("short")

    def test_hash_too_long_raises(self):
        with pytest.raises(ValueError, match="password length"):
            hash_password("x" * 129)

    def test_different_calls_produce_different_hashes(self):
        h1 = hash_password("testPassword123")
        h2 = hash_password("testPassword123")
        assert h1 != h2  # Different salts


class TestVerifyPassword:
    """Tests for verify_password()."""

    def test_verify_correct_password(self):
        h = hash_password("mySecretPass")
        assert verify_password("mySecretPass", h) is True

    def test_verify_wrong_password(self):
        h = hash_password("mySecretPass")
        assert verify_password("wrongPassword", h) is False

    def test_verify_empty_hash_returns_false(self):
        assert verify_password("testPassword", "") is False

    def test_verify_none_hash_returns_false(self):
        assert verify_password("testPassword", None) is False

    def test_verify_corrupted_hash_returns_false(self):
        assert verify_password("testPassword", "not-a-valid-hash") is False
