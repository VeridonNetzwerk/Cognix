"""Alembic environment using async SQLAlchemy + Base metadata."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# settings import happens lazily inside each function so it can also be used
# when running 'alembic' CLI directly (which sets up its own context).
from config.settings import get_settings
from database.base import Base
from database import models  # noqa: F401 - registers models on metadata

alembic_config = context.config

if alembic_config.config_file_name is not None:
    fileConfig(alembic_config.config_file_name)

target_metadata = Base.metadata


def _db_url() -> str:
    """Return the database URL directly from settings — bypasses ConfigParser
    interpolation which chokes on percent-encoded characters (e.g. %5E)."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    url = _db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    # Create the engine directly from settings — never via ConfigParser —
    # so special chars in passwords (%5E, %2B, etc.) are handled correctly.
    connectable = create_async_engine(_db_url(), poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
