"""Tests for auth service: login, lockout, refresh rotation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from bot.database.models.auth.web_user import RefreshToken, WebRole, WebUser
from web.schemas.auth import LoginRequest
from web.security.passwords import hash_password
from web.security.tokens import hash_refresh_token, issue_refresh_token
from web.services.auth_service import (
    AuthError,
    authenticate,
    issue_session,
    revoke_all_sessions,
    rotate_refresh,
)


@pytest.fixture
def make_user(db_sessionmaker):
    """Factory to create users in the test DB."""
    created = []

    async def _make(
        username="testuser",
        password="test-password-123",
        role=WebRole.ADMIN,
        active=True,
    ):
        async with db_sessionmaker() as s:
            user = WebUser(
                id=uuid.uuid4(),
                username=username,
                email=f"{username}@example.com",
                password_hash=hash_password(password),
                role=role,
                is_active=active,
            )
            s.add(user)
            await s.commit()
            created.append(user.id)
            return user

    return _make


class TestAuthenticate:
    """auth_service.authenticate()"""

    async def test_authenticate_success(self, db_sessionmaker, make_user):
        await make_user("authuser", "correct-password")
        async with db_sessionmaker() as s:
            user = await authenticate(s, LoginRequest(
                username="authuser",
                password="correct-password",
            ))
            assert user.username == "authuser"

    async def test_authenticate_wrong_password(self, db_sessionmaker, make_user):
        await make_user("wrongpw", "correct-password")
        async with db_sessionmaker() as s:
            with pytest.raises(AuthError, match="invalid credentials"):
                await authenticate(s, LoginRequest(
                    username="wrongpw",
                    password="wrong-password",
                ))

    async def test_authenticate_nonexistent_user(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            with pytest.raises(AuthError, match="invalid credentials"):
                await authenticate(s, LoginRequest(
                    username="ghost",
                    password="whatever",
                ))

    async def test_authenticate_inactive_user(self, db_sessionmaker, make_user):
        await make_user("inactive", "correct-password", active=False)
        async with db_sessionmaker() as s:
            with pytest.raises(AuthError, match="invalid credentials"):
                await authenticate(s, LoginRequest(
                    username="inactive",
                    password="correct-password",
                ))

    async def test_authenticate_locked_account(self, db_sessionmaker, make_user):
        await make_user("locked", "correct-password")
        # Lock the account
        async with db_sessionmaker() as s:
            user = await s.scalar(select(WebUser).where(WebUser.username == "locked"))
            user.locked_until = datetime.now(UTC) + timedelta(minutes=15)
            await s.commit()

        async with db_sessionmaker() as s:
            with pytest.raises(AuthError, match="account locked"):
                await authenticate(s, LoginRequest(
                    username="locked",
                    password="correct-password",
                ))

    async def test_authenticate_increments_failed_count(self, db_sessionmaker, make_user):
        await make_user("failcount", "correct-password")
        # Fail once
        async with db_sessionmaker() as s:
            with pytest.raises(AuthError):
                await authenticate(s, LoginRequest(
                    username="failcount",
                    password="wrong",
                ))
            await s.commit()

        # Check failed_login_count incremented
        async with db_sessionmaker() as s:
            user = await s.scalar(select(WebUser).where(WebUser.username == "failcount"))
            assert user.failed_login_count == 1

    async def test_authenticate_resets_on_success(self, db_sessionmaker, make_user):
        await make_user("resetsuccess", "correct-password")
        # Fail once
        async with db_sessionmaker() as s:
            with pytest.raises(AuthError):
                await authenticate(s, LoginRequest(
                    username="resetsuccess",
                    password="wrong",
                ))
            await s.commit()

        # Login successfully
        async with db_sessionmaker() as s:
            await authenticate(s, LoginRequest(
                username="resetsuccess",
                password="correct-password",
            ))
            await s.commit()

        async with db_sessionmaker() as s:
            user = await s.scalar(select(WebUser).where(WebUser.username == "resetsuccess"))
            assert user.failed_login_count == 0
            assert user.locked_until is None


class TestIssueSession:
    """auth_service.issue_session()"""

    async def test_issue_session_creates_refresh_token(self, db_sessionmaker, make_user):
        user = await make_user("sessionuser", "test-password-123")
        async with db_sessionmaker() as s:
            access, refresh, exp = await issue_session(s, user, user_agent="test-agent")
            await s.commit()

        assert isinstance(access, str)
        assert isinstance(refresh, str)
        assert exp > datetime.now(UTC)

        # Verify refresh token was stored
        async with db_sessionmaker() as s:
            rt = await s.scalar(
                select(RefreshToken).where(
                    RefreshToken.token_hash == hash_refresh_token(refresh)
                )
            )
            assert rt is not None
            assert rt.user_agent == "test-agent"


class TestRotateRefresh:
    """auth_service.rotate_refresh()"""

    async def test_rotate_success(self, db_sessionmaker, make_user):
        user = await make_user("rotateuser", "test-password-123")
        async with db_sessionmaker() as s:
            _, refresh, _ = await issue_session(s, user)
            await s.commit()

        async with db_sessionmaker() as s:
            new_access, new_refresh, new_exp, remember = await rotate_refresh(
                s, refresh, user_agent="test"
            )
            await s.commit()

        assert new_access
        assert new_refresh != refresh
        assert new_exp > datetime.now(UTC)

    async def test_rotate_invalid_token(self, db_sessionmaker):
        async with db_sessionmaker() as s:
            with pytest.raises(AuthError, match="invalid refresh"):
                await rotate_refresh(s, "invalid-token")

    async def test_rotate_revoked_token(self, db_sessionmaker, make_user):
        user = await make_user("revokeduser", "test-password-123")
        async with db_sessionmaker() as s:
            _, refresh, _ = await issue_session(s, user)
            await s.commit()

        # Use it once (revokes it)
        async with db_sessionmaker() as s:
            await rotate_refresh(s, refresh)
            await s.commit()

        # Try to use the old token again
        async with db_sessionmaker() as s:
            with pytest.raises(AuthError):
                await rotate_refresh(s, refresh)


class TestRevokeAllSessions:
    """auth_service.revoke_all_sessions()"""

    async def test_revoke_all(self, db_sessionmaker, make_user):
        user = await make_user("revokeuser", "test-password-123")
        async with db_sessionmaker() as s:
            await issue_session(s, user)
            await issue_session(s, user)
            await s.commit()

        async with db_sessionmaker() as s:
            await revoke_all_sessions(s, user.id)
            await s.commit()

        async with db_sessionmaker() as s:
            active = (
                await s.scalars(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user.id,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            ).all()
            assert len(active) == 0
