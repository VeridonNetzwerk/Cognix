"""Google OAuth (OIDC) using authlib."""

from __future__ import annotations

from authlib.integrations.starlette_client import OAuth

from config.settings import get_settings

_oauth: OAuth | None = None


def get_oauth() -> OAuth:
    global _oauth
    if _oauth is not None:
        return _oauth
    settings = get_settings()
    oauth = OAuth()
    oauth.register(
        name="google",
        client_id=settings.google_oauth_client_id or None,
        client_secret=settings.google_oauth_client_secret or None,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    _oauth = oauth
    return oauth
