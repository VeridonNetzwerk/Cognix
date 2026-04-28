"""Backups cog: snapshot and restore roles/channels/permissions.

The IPC ``backup.snapshot`` and ``backup.restore`` commands are the
authoritative entry points used by the dashboard. Slash commands live
under the ``/backup`` group and persist snapshots in the ``backups``
table with the JSON payload encrypted via :mod:`config.crypto`.

Subcommands:

* ``/backup create [name] [message_limit]`` - snapshot the guild.
* ``/backup list``                          - list saved backups.
* ``/backup load <id>``                     - restore a saved backup.
* ``/backup delete <id>``                   - remove a saved backup.

``message_limit`` is currently informational; channel history is *not*
captured. It is kept on the public surface to match the documented UX
and to leave room for a future implementation.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, select

from bot.utils.embeds import err_embed, info_embed, ok_embed
from config.crypto import CryptoError, decrypt_secret, encrypt_secret
from config.logging import get_logger
from database import db_session
from database.models.backup import Backup
from database.models.server import Server

log = get_logger("bot.cogs.backups")

FOOTER_TEXT = "Powered by Cognix \u00b7 Made by \u98df\u3079\u7269"


# --------------------------------------------------------------------- helpers


def _serialize_role(role: discord.Role) -> dict[str, Any]:
    return {
        "id": role.id,
        "name": role.name,
        "color": role.color.value,
        "hoist": role.hoist,
        "mentionable": role.mentionable,
        "permissions": role.permissions.value,
        "position": role.position,
    }


def _serialize_overwrite(
    target: discord.Role | discord.Member, ow: discord.PermissionOverwrite
) -> dict[str, Any]:
    allow, deny = ow.pair()
    return {
        "target_id": target.id,
        "type": "role" if isinstance(target, discord.Role) else "member",
        "allow": allow.value,
        "deny": deny.value,
    }


def _serialize_channel(ch: discord.abc.GuildChannel) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": ch.id,
        "name": ch.name,
        "type": ch.type.value,
        "position": ch.position,
        "category_id": ch.category_id,
        "overwrites": [_serialize_overwrite(t, o) for t, o in ch.overwrites.items()],
    }
    if isinstance(ch, discord.TextChannel):
        base.update(topic=ch.topic, nsfw=ch.nsfw, slowmode_delay=ch.slowmode_delay)
    elif isinstance(ch, discord.VoiceChannel):
        base.update(bitrate=ch.bitrate, user_limit=ch.user_limit)
    return base


def _info(title: str, description: str) -> discord.Embed:
    e = info_embed(title, description)
    e.set_footer(text=FOOTER_TEXT)
    return e


def _ok(title: str, description: str) -> discord.Embed:
    e = ok_embed(title, description)
    e.set_footer(text=FOOTER_TEXT)
    return e


def _err(title: str, description: str) -> discord.Embed:
    e = err_embed(title, description)
    e.set_footer(text=FOOTER_TEXT)
    return e


# --------------------------------------------------------------------- cog


class _RestoreConfirmView(discord.ui.View):
    """Two-button confirm dialog for /backup load."""

    def __init__(self, cog: "Backups", backup_id: uuid.UUID, payload: dict[str, Any]) -> None:
        super().__init__(timeout=120)
        self.cog = cog
        self.backup_id = backup_id
        self.payload = payload

    @discord.ui.button(label="✅ Bestätigen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.guild is None:
            return
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            embed=_info("Wird wiederhergestellt …", "Bitte warten."), view=self
        )
        try:
            await self.cog._restore_into(interaction.guild, self.payload, purge=True)
        except Exception as exc:  # noqa: BLE001
            log.exception("backup_restore_failed", error=str(exc))
            await interaction.followup.send(
                embed=_err("Restore failed", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=_ok(
                "Backup wiederhergestellt",
                f"`{self.backup_id}` wurde mit Purge angewendet.",
            ),
            ephemeral=True,
        )

    @discord.ui.button(label="❌ Abbrechen", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        for child in self.children:
            child.disabled = True  # type: ignore[attr-defined]
        await interaction.response.edit_message(
            embed=_info("Abgebrochen", "Es wurde nichts verändert."), view=self
        )


class Backups(commands.Cog):
    backup_group = app_commands.Group(
        name="backup", description="Manage server backups"
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        ipc = getattr(bot, "ipc", None)
        if ipc is not None:
            ipc.register("backup.snapshot", self._ipc_snapshot)
            ipc.register("backup.restore", self._ipc_restore)
            ipc.register("backup.create", self._ipc_create)
            ipc.register("backup.list", self._ipc_list)
            ipc.register("backup.delete", self._ipc_delete)

    # ----------------------------------------------------- snapshot logic

    async def _snapshot(
        self, guild: discord.Guild, *, message_limit: int = 0
    ) -> dict[str, Any]:
        return {
            "guild_id": guild.id,
            "name": guild.name,
            "message_limit": int(message_limit),
            "roles": [_serialize_role(r) for r in guild.roles if not r.is_default()],
            "channels": [
                _serialize_channel(c)
                for c in sorted(guild.channels, key=lambda x: (x.position, x.id))
            ],
        }

    async def _ensure_server_row(self, guild: discord.Guild) -> None:
        async with db_session() as s:
            existing = await s.get(Server, guild.id)
            if existing is None:
                s.add(
                    Server(
                        id=guild.id,
                        name=guild.name,
                        member_count=guild.member_count or 0,
                    )
                )

    async def _persist_backup(
        self,
        guild: discord.Guild,
        *,
        name: str,
        created_by: int,
        snapshot: dict[str, Any],
        description: str = "",
    ) -> Backup:
        await self._ensure_server_row(guild)
        payload_json = json.dumps(snapshot, ensure_ascii=False)
        token = encrypt_secret(payload_json)
        async with db_session() as s:
            b = Backup(
                server_id=guild.id,
                name=name or f"backup-{guild.name}",
                description=description,
                created_by=created_by,
                payload_encrypted=token,
                payload_size_bytes=len(payload_json.encode("utf-8")),
                schema_version=1,
                summary={
                    "roles": len(snapshot["roles"]),
                    "channels": len(snapshot["channels"]),
                    "guild_name": guild.name,
                    "message_limit": snapshot.get("message_limit", 0),
                },
            )
            s.add(b)
            await s.flush()
            await s.refresh(b)
            return b

    async def _load_backup_payload(self, backup_id: uuid.UUID) -> dict[str, Any] | None:
        async with db_session() as s:
            b = await s.get(Backup, backup_id)
            if b is None:
                return None
            try:
                plaintext = decrypt_secret(b.payload_encrypted)
            except CryptoError as exc:
                log.error("backup_decrypt_failed", error=str(exc))
                return None
            return json.loads(plaintext)

    async def _restore_into(
        self, guild: discord.Guild, payload: dict[str, Any], *, purge: bool = False
    ) -> None:
        backup_role_names = {r["name"] for r in payload["roles"]}
        backup_channel_names = {c["name"] for c in payload["channels"]}
        bot_member = guild.me

        # ---- purge: delete current items not present in backup --------
        if purge:
            for ch in list(guild.channels):
                if ch.name in backup_channel_names:
                    continue
                try:
                    await ch.delete(reason="CogniX restore (purge)")
                except discord.HTTPException as exc:
                    log.warning("backup_purge_channel_failed", name=ch.name, error=str(exc))
            for role in list(guild.roles):
                if role.is_default() or role.managed:
                    continue
                if bot_member is not None and role in bot_member.roles and role >= bot_member.top_role:
                    continue
                if role.name in backup_role_names:
                    continue
                try:
                    await role.delete(reason="CogniX restore (purge)")
                except discord.HTTPException as exc:
                    log.warning("backup_purge_role_failed", name=role.name, error=str(exc))

        # ---- restore roles (skip @everyone, top-down by position desc)
        existing_roles = {r.name: r for r in guild.roles}
        for r in sorted(payload["roles"], key=lambda x: -x["position"]):
            if r["name"] in existing_roles:
                continue
            try:
                await guild.create_role(
                    name=r["name"],
                    permissions=discord.Permissions(r["permissions"]),
                    colour=discord.Colour(r["color"]),
                    hoist=r["hoist"],
                    mentionable=r["mentionable"],
                    reason="CogniX backup restore",
                )
            except discord.HTTPException as exc:
                log.warning("backup_role_create_failed", role=r["name"], error=str(exc))

        chans_by_type: dict[int, list[dict[str, Any]]] = {}
        for c in payload["channels"]:
            chans_by_type.setdefault(c["type"], []).append(c)

        # 4 = category
        for c in chans_by_type.get(4, []):
            if not discord.utils.get(guild.categories, name=c["name"]):
                try:
                    await guild.create_category(c["name"], reason="CogniX restore")
                except discord.HTTPException as exc:
                    log.warning("backup_category_failed", name=c["name"], error=str(exc))

        for c in payload["channels"]:
            if c["type"] == 4:
                continue
            if discord.utils.get(guild.channels, name=c["name"]):
                continue
            cat_name = next(
                (
                    x["name"]
                    for x in chans_by_type.get(4, [])
                    if x["id"] == c.get("category_id")
                ),
                "",
            )
            cat = discord.utils.get(guild.categories, name=cat_name) if cat_name else None
            try:
                if c["type"] == 0:
                    await guild.create_text_channel(
                        c["name"],
                        category=cat,
                        topic=c.get("topic"),
                        nsfw=c.get("nsfw", False),
                        slowmode_delay=c.get("slowmode_delay", 0),
                        reason="CogniX restore",
                    )
                elif c["type"] == 2:
                    await guild.create_voice_channel(
                        c["name"],
                        category=cat,
                        bitrate=c.get("bitrate", 64000),
                        user_limit=c.get("user_limit", 0),
                        reason="CogniX restore",
                    )
            except discord.HTTPException as exc:
                log.warning("backup_channel_failed", name=c["name"], error=str(exc))

    @staticmethod
    def _diff(guild: discord.Guild, payload: dict[str, Any]) -> dict[str, int]:
        backup_role_names = {r["name"] for r in payload["roles"]}
        backup_channel_names = {c["name"] for c in payload["channels"]}
        current_role_names = {r.name for r in guild.roles if not r.is_default() and not r.managed}
        current_channel_names = {c.name for c in guild.channels}
        return {
            "roles_to_create": len(backup_role_names - current_role_names),
            "roles_to_delete": len(current_role_names - backup_role_names),
            "channels_to_create": len(backup_channel_names - current_channel_names),
            "channels_to_delete": len(current_channel_names - backup_channel_names),
            "extras_to_purge": (
                len(current_role_names - backup_role_names)
                + len(current_channel_names - backup_channel_names)
            ),
        }

    # ----------------------------------------------------- slash commands

    @backup_group.command(name="create", description="Create a new server backup")
    @app_commands.describe(
        name="Friendly name for this backup",
        message_limit="Reserved (channel history capture, not yet implemented)",
    )
    @app_commands.default_permissions(administrator=True)
    async def backup_create(
        self,
        interaction: discord.Interaction,
        name: str | None = None,
        message_limit: int | None = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=_err("Guild only", "Run this command inside a server."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            snap = await self._snapshot(
                interaction.guild, message_limit=int(message_limit or 0)
            )
            backup = await self._persist_backup(
                interaction.guild,
                name=(name or f"backup-{interaction.guild.name}").strip()[:128],
                created_by=interaction.user.id,
                snapshot=snap,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("backup_create_failed", error=str(exc))
            await interaction.followup.send(
                embed=_err("Backup failed", str(exc)), ephemeral=True
            )
            return
        await interaction.followup.send(
            embed=_ok(
                "Backup created",
                f"**{backup.name}** \u2014 `{backup.id}`\n"
                f"Roles: {len(snap['roles'])}, Channels: {len(snap['channels'])}",
            ),
            ephemeral=True,
        )

    @backup_group.command(name="list", description="List saved backups for this server")
    @app_commands.default_permissions(administrator=True)
    async def backup_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=_err("Guild only", "Run inside a server."), ephemeral=True
            )
            return
        async with db_session() as s:
            rows = (
                await s.scalars(
                    select(Backup)
                    .where(Backup.server_id == interaction.guild.id)
                    .order_by(desc(Backup.created_at))
                    .limit(25)
                )
            ).all()
        if not rows:
            await interaction.response.send_message(
                embed=_info("No backups", "There are no saved backups for this server."),
                ephemeral=True,
            )
            return
        lines = [
            f"\u2022 `{b.id}` \u2014 **{b.name}** ({b.summary.get('roles', 0)}R / "
            f"{b.summary.get('channels', 0)}C) \u2014 "
            f"{b.created_at.strftime('%Y-%m-%d %H:%M UTC')}"
            for b in rows
        ]
        await interaction.response.send_message(
            embed=_info(f"Backups ({len(rows)})", "\n".join(lines)),
            ephemeral=True,
        )

    async def _backup_id_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        async with db_session() as s:
            rows = (
                await s.scalars(
                    select(Backup)
                    .where(Backup.server_id == interaction.guild.id)
                    .order_by(desc(Backup.created_at))
                    .limit(25)
                )
            ).all()
        cur = (current or "").lower()
        choices: list[app_commands.Choice[str]] = []
        for b in rows:
            uid = str(b.id)
            label = f"{uid[:8]} ({b.name}, {b.created_at.strftime('%Y-%m-%d')})"
            if cur and cur not in uid.lower() and cur not in b.name.lower():
                continue
            choices.append(app_commands.Choice(name=label[:100], value=uid))
            if len(choices) >= 25:
                break
        return choices

    @backup_group.command(name="load", description="Restore a saved backup into this server")
    @app_commands.describe(backup_id="UUID of the backup to restore")
    @app_commands.autocomplete(backup_id=_backup_id_autocomplete)
    @app_commands.default_permissions(administrator=True)
    async def backup_load(
        self, interaction: discord.Interaction, backup_id: str
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message(
                embed=_err("Guild only", "Run inside a server."), ephemeral=True
            )
            return
        try:
            uid = uuid.UUID(backup_id)
        except ValueError:
            await interaction.response.send_message(
                embed=_err("Invalid id", "Provide a valid backup UUID."),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        payload = await self._load_backup_payload(uid)
        if payload is None:
            await interaction.followup.send(
                embed=_err("Not found", "No backup with that id, or decrypt failed."),
                ephemeral=True,
            )
            return
        diff = self._diff(interaction.guild, payload)
        embed = _info(
            "Bestätige Backup-Wiederherstellung",
            (
                f"**Backup:** `{uid}`\n\n"
                f"\u2022 Rollen anzulegen: **{diff['roles_to_create']}**\n"
                f"\u2022 Rollen zu löschen: **{diff['roles_to_delete']}**\n"
                f"\u2022 Kanäle anzulegen: **{diff['channels_to_create']}**\n"
                f"\u2022 Kanäle zu löschen: **{diff['channels_to_delete']}**\n"
                f"\u2022 Neue/zusätzliche Elemente werden gepurged: **{diff['extras_to_purge']}**\n\n"
                "Der Server wird in den exakten Zustand des Backups versetzt."
            ),
        )
        view = _RestoreConfirmView(self, uid, payload)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @backup_group.command(name="delete", description="Delete a saved backup")
    @app_commands.describe(backup_id="UUID of the backup to delete")
    @app_commands.default_permissions(administrator=True)
    async def backup_delete(
        self, interaction: discord.Interaction, backup_id: str
    ) -> None:
        try:
            uid = uuid.UUID(backup_id)
        except ValueError:
            await interaction.response.send_message(
                embed=_err("Invalid id", "Provide a valid backup UUID."),
                ephemeral=True,
            )
            return
        async with db_session() as s:
            b = await s.get(Backup, uid)
            if b is None:
                await interaction.response.send_message(
                    embed=_err("Not found", "No backup with that id."),
                    ephemeral=True,
                )
                return
            await s.delete(b)
        await interaction.response.send_message(
            embed=_ok("Backup deleted", f"`{uid}` was removed."), ephemeral=True
        )

    # ----------------------------------------------------- IPC handlers

    async def _ipc_snapshot(self, p: dict[str, Any]) -> dict[str, Any]:
        guild = self.bot.get_guild(int(p["server_id"]))
        if guild is None:
            return {}
        return await self._snapshot(guild, message_limit=int(p.get("message_limit", 0)))

    async def _ipc_create(self, p: dict[str, Any]) -> dict[str, Any]:
        guild = self.bot.get_guild(int(p["server_id"]))
        if guild is None:
            return {"status": "error", "error": "guild not found"}
        snap = await self._snapshot(guild, message_limit=int(p.get("message_limit", 0)))
        b = await self._persist_backup(
            guild,
            name=str(p.get("name") or f"backup-{guild.name}")[:128],
            created_by=int(p.get("created_by") or 0),
            snapshot=snap,
            description=str(p.get("description") or ""),
        )
        return {"status": "ok", "backup_id": str(b.id)}

    async def _ipc_list(self, p: dict[str, Any]) -> dict[str, Any]:
        async with db_session() as s:
            q = select(Backup).order_by(desc(Backup.created_at))
            if p.get("server_id"):
                q = q.where(Backup.server_id == int(p["server_id"]))
            rows = (await s.scalars(q)).all()
        return {
            "backups": [
                {
                    "id": str(b.id),
                    "name": b.name,
                    "server_id": b.server_id,
                    "created_at": b.created_at.isoformat(),
                    "summary": dict(b.summary or {}),
                }
                for b in rows
            ]
        }

    async def _ipc_delete(self, p: dict[str, Any]) -> dict[str, Any]:
        try:
            uid = uuid.UUID(str(p["backup_id"]))
        except (KeyError, ValueError):
            return {"status": "error", "error": "backup_id required"}
        async with db_session() as s:
            b = await s.get(Backup, uid)
            if b is None:
                return {"status": "error", "error": "not found"}
            await s.delete(b)
        return {"status": "ok"}

    async def _ipc_restore(self, p: dict[str, Any]) -> dict[str, Any]:
        target_id = int(p["target_server_id"])
        guild = self.bot.get_guild(target_id)
        if guild is None:
            raise RuntimeError("target guild not found")

        payload = p.get("payload")
        if payload is None and p.get("backup_id"):
            payload = await self._load_backup_payload(uuid.UUID(str(p["backup_id"])))
        if payload is None:
            return {"status": "error", "error": "no payload or backup_id"}

        # BUG #8 fix: web-triggered restores must also purge so the server
        # ends up in the exact state of the backup (not merely additive).
        purge = bool(p.get("purge", True))
        await self._restore_into(guild, payload, purge=purge)
        return {"status": "ok"}


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Backups(bot))
