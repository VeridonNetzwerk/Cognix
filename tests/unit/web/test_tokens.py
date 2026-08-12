"""Tests for web.security.tokens — JWT issue/verify."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from web.security.tokens import (
    TokenError,
    decode_token,
    hash_refresh_token,
    issue_access_token,
    issue_refresh_token,
)


class TestAccessTokens:
    """Tests for access token issue/decode."""

    def test_issue_and_decode(self):
        token = issue_access_token(subject="user-123", role="ADMIN")
        payload = decode_token(token, expected_type="access")
        assert payload["sub"] == "user-123"
        assert payload["role"] == "ADMIN"
        assert payload["typ"] == "access"

    def test_issue_with_remember_me(self):
        token = issue_access_token(subject="user-123", role="ADMIN", remember_me=True)
        payload = decode_token(token, expected_type="access")
        assert payload["rm"] is True

    def test_issue_without_remember_me(self):
        token = issue_access_token(subject="user-123", role="ADMIN", remember_me=False)
        payload = decode_token(token, expected_type="access")
        assert payload["rm"] is False

    def test_decode_wrong_type_raises(self):
        token = issue_access_token(subject="user-123", role="ADMIN")
        with pytest.raises(TokenError, match="unexpected token type"):
            decode_token(token, expected_type="refresh")

    def test_decode_invalid_token_raises(self):
        with pytest.raises(TokenError):
            decode_token("invalid.token.here")

    def test_decode_garbage_raises(self):
        with pytest.raises(TokenError):
            decode_token("not-a-jwt-at-all")

    def test_token_has_jti(self):
        token = issue_access_token(subject="user-123", role="ADMIN")
        payload = decode_token(token)
        assert "jti" in payload
        assert len(payload["jti"]) == 32  # uuid4().hex

    def test_token_has_expiry(self):
        token = issue_access_token(subject="user-123", role="ADMIN")
        payload = decode_token(token)
        assert "exp" in payload
        assert "iat" in payload
        assert payload["exp"] > payload["iat"]


class TestRefreshTokens:
    """Tests for refresh token issue/decode."""

    def test_issue_and_decode(self):
        family_id = uuid.uuid4()
        token, expires = issue_refresh_token(subject="user-123", family_id=family_id)
        assert isinstance(token, str)
        assert isinstance(expires, datetime)
        payload = decode_token(token, expected_type="refresh")
        assert payload["sub"] == "user-123"
        assert payload["fam"] == family_id.hex
        assert payload["typ"] == "refresh"

    def test_refresh_token_has_random_component(self):
        family_id = uuid.uuid4()
        token1, _ = issue_refresh_token(subject="user-123", family_id=family_id)
        token2, _ = issue_refresh_token(subject="user-123", family_id=family_id)
        payload1 = decode_token(token1, expected_type="refresh")
        payload2 = decode_token(token2, expected_type="refresh")
        assert payload1["rnd"] != payload2["rnd"], \
            "Refresh tokens should have unique random components"

    def test_refresh_expiry_is_future(self):
        family_id = uuid.uuid4()
        _, expires = issue_refresh_token(subject="user-123", family_id=family_id)
        now = datetime.now(UTC)
        assert expires > now


class TestHashRefreshToken:
    """Tests for hash_refresh_token()."""

    def test_hash_is_deterministic(self):
        token = "test-token-value"
        h1 = hash_refresh_token(token)
        h2 = hash_refresh_token(token)
        assert h1 == h2

    def test_hash_is_hex_string(self):
        h = hash_refresh_token("test-token")
        assert len(h) == 64  # SHA-256 hex digest
        int(h, 16)  # Should be valid hex

    def test_different_tokens_different_hashes(self):
        assert hash_refresh_token("token-a") != hash_refresh_token("token-b")
