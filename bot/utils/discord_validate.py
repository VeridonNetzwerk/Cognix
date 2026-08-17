"""Discord token + application ID validation helpers.

Makes a lightweight call to the Discord API to verify that a bot token
is valid and (optionally) that the application ID matches the bot's
own user ID.
"""

from __future__ import annotations

import httpx
from dataclasses import dataclass

DISCORD_API_BASE = "https://discord.com/api/v10"


@dataclass
class TokenValidationResult:
    valid: bool
    error: str | None = None
    bot_user_id: str | None = None
    bot_username: str | None = None


async def validate_bot_token(token: str) -> TokenValidationResult:
    """Verify a bot token by calling GET /users/@me.

    Returns a TokenValidationResult with success info and the bot's
    user ID (which should match the application/bot ID).
    """
    token = token.strip()
    if not token:
        return TokenValidationResult(valid=False, error="Bot token is required")

    if "." not in token:
        return TokenValidationResult(
            valid=False, error="Invalid token format — a bot token must contain three dot-separated parts"
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{DISCORD_API_BASE}/users/@me",
                headers={"Authorization": f"Bot {token}"},
            )
    except httpx.TimeoutException:
        return TokenValidationResult(
            valid=False, error="Discord API timed out — check your internet connection and try again"
        )
    except httpx.RequestError as exc:
        return TokenValidationResult(
            valid=False, error=f"Could not reach Discord API: {exc}"
        )

    if resp.status_code == 401:
        return TokenValidationResult(
            valid=False, error="Invalid bot token — Discord rejected the credentials"
        )
    if resp.status_code == 403:
        return TokenValidationResult(
            valid=False, error="Bot token lacks required scopes — ensure this is a bot token, not a user token"
        )
    if resp.status_code != 200:
        return TokenValidationResult(
            valid=False, error=f"Discord API returned HTTP {resp.status_code}"
        )

    data = resp.json()
    bot_id = data.get("id", "")
    bot_name = data.get("username", "")

    if not bot_id:
        return TokenValidationResult(
            valid=False, error="Discord API response did not include a bot user ID"
        )

    return TokenValidationResult(valid=True, bot_user_id=str(bot_id), bot_username=bot_name)


async def validate_bot_token_and_app_id(
    token: str, application_id: str
) -> TokenValidationResult:
    """Validate the bot token and, if an application ID is provided,
    check that it matches the bot's user ID."""
    result = await validate_bot_token(token)
    if not result.valid:
        return result

    app_id = application_id.strip()
    if app_id and result.bot_user_id and app_id != result.bot_user_id:
        return TokenValidationResult(
            valid=False,
            error=(
                f"Application ID mismatch: the token belongs to bot user "
                f"'{result.bot_username}' (ID {result.bot_user_id}), "
                f"but the provided application ID is {app_id}"
            ),
        )

    return result
