"""CLI helper to bootstrap an admin user.

Usage::

    python scripts/create_admin.py <username> <email> <password>
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from database import db_session, init_engine
from database.models.web_user import WebRole, WebUser
from web.security.passwords import hash_password


async def main(username: str, email: str, password: str) -> int:
    init_engine()
    async with db_session() as s:
        existing = await s.scalar(select(WebUser).where(WebUser.username == username))
        if existing:
            print(f"user '{username}' already exists")
            return 1
        s.add(
            WebUser(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role=WebRole.ADMIN,
                is_active=True,
            )
        )
    print(f"created admin user '{username}'")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3])))
