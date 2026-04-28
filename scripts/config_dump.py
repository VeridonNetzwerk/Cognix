"""Config snapshot / restore CLI (Phase 9 ops tool).

Exports SystemConfig + every ServerConfig + CogState rows to a JSON file
(secrets remain encrypted as stored). Restore writes the same rows back.
Bot tokens / OAuth secrets stay readable only by an instance with the
matching ``MASTER_KEY``.

Usage:
    python scripts/config_dump.py export <path.json>
    python scripts/config_dump.py import <path.json>
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from database import db_session, init_engine
from database.models.cog_state import CogState
from database.models.server_config import ServerConfig
from database.models.system_config import SystemConfig


async def export_config(path: Path) -> int:
    init_engine()
    async with db_session() as s:
        sc = await s.scalar(select(SystemConfig).where(SystemConfig.id == 1))
        servers = (await s.scalars(select(ServerConfig))).all()
        cogs = (await s.scalars(select(CogState))).all()

    def _row(obj: object) -> dict:
        d: dict = {}
        for c in obj.__table__.columns:  # type: ignore[attr-defined]
            v = getattr(obj, c.name)
            d[c.name] = v.isoformat() if hasattr(v, "isoformat") else v
        return d

    payload = {
        "version": 1,
        "system_config": _row(sc) if sc else None,
        "server_configs": [_row(x) for x in servers],
        "cog_states": [_row(x) for x in cogs],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(f"wrote {path} ({len(servers)} servers, {len(cogs)} cog states)")
    return 0


async def import_config(path: Path) -> int:
    init_engine()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        print("unsupported version")
        return 2
    async with db_session() as s:
        sc_data = payload.get("system_config")
        if sc_data:
            sc = await s.scalar(select(SystemConfig).where(SystemConfig.id == 1))
            if sc is None:
                sc = SystemConfig(id=1)
                s.add(sc)
            for k, v in sc_data.items():
                if k in ("id", "created_at", "updated_at"):
                    continue
                if hasattr(sc, k):
                    setattr(sc, k, v)
        for row in payload.get("server_configs", []):
            existing = await s.scalar(
                select(ServerConfig).where(ServerConfig.server_id == row["server_id"])
            )
            target = existing or ServerConfig(server_id=row["server_id"])
            for k, v in row.items():
                if k in ("id", "created_at", "updated_at"):
                    continue
                if hasattr(target, k):
                    setattr(target, k, v)
            if existing is None:
                s.add(target)
        for row in payload.get("cog_states", []):
            s.merge(CogState(**{k: v for k, v in row.items() if k != "created_at" and k != "updated_at"}))
    print("import complete")
    return 0


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("export", "import"):
        print(__doc__)
        return 2
    path = Path(sys.argv[2])
    coro = export_config(path) if sys.argv[1] == "export" else import_config(path)
    return asyncio.run(coro)


if __name__ == "__main__":
    sys.exit(main())
