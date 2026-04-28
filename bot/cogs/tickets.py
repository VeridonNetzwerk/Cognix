"""Tickets cog: thread-based support tickets with button creation.

Closing a ticket follows this flow (per product spec):

1. Respond to the interaction immediately so Discord doesn't show
   "Interaction failed".
2. Build a transcript of the thread for archival.
3. Persist the ticket as ``ARCHIVED`` in the database including the
   transcript and a closing reason.
4. Remove visibility from the channel (lock + remove members).
5. Delete the underlying Discord thread.

There is **no auto-close**: tickets stay open until a moderator closes
them via the in-thread panel or ``/ticket-close``.
"""

from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.utils.embeds import err_embed, info_embed, ok_embed
from config.logging import get_logger
from database import db_session
from database.models.server import Server
from database.models.server_config import ServerConfig
from database.models.ticket import Ticket, TicketMessage, TicketStatus

log = get_logger("bot.cogs.tickets")

FOOTER_TEXT = "Powered by Cognix \u00b7 Made by \u98df\u3079\u7269"


class TicketOpenView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open Ticket",
        style=discord.ButtonStyle.primary,
        custom_id="cognix:ticket:open",
    )
    async def open_ticket(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        cog: Tickets | None = interaction.client.get_cog("Tickets")  # type: ignore[assignment]
        if cog is None:
            await interaction.response.send_message("Tickets not loaded", ephemeral=True)
            return
        await cog.create_ticket(interaction)


class TicketControlView(discord.ui.View):
    """Per-ticket control panel posted at the start of every ticket thread."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Claim",
        style=discord.ButtonStyle.secondary,
        custom_id="cognix:ticket:claim",
        emoji="\N{RAISED HAND}",
    )
    async def claim(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog: Tickets | None = interaction.client.get_cog("Tickets")  # type: ignore[assignment]
        if cog is None:
            await interaction.response.send_message("Tickets not loaded", ephemeral=True)
            return
        await cog._handle_claim(interaction)

    @discord.ui.button(
        label="Close",
        style=discord.ButtonStyle.danger,
        custom_id="cognix:ticket:close",
        emoji="\N{LOCK}",
    )
    async def close(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        cog: Tickets | None = interaction.client.get_cog("Tickets")  # type: ignore[assignment]
        if cog is None:
            await interaction.response.send_message("Tickets not loaded", ephemeral=True)
            return
        await cog._handle_close_button(interaction)

    @discord.ui.button(
        label="Transcript",
        style=discord.ButtonStyle.primary,
        custom_id="cognix:ticket:transcript",
        emoji="\N{PAGE FACING UP}",
    )
    async def transcript(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ) -> None:
        cog: Tickets | None = interaction.client.get_cog("Tickets")  # type: ignore[assignment]
        if cog is None:
            await interaction.response.send_message("Tickets not loaded", ephemeral=True)
            return
        await cog._handle_transcript(interaction)


class Tickets(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(TicketOpenView())
        bot.add_view(TicketControlView())
        ipc = getattr(bot, "ipc", None)
        if ipc is not None:
            ipc.register("ticket.close", self._ipc_close)

    # ------------------------------------------------------------- helpers

    async def _ensure_server(self, guild: discord.Guild) -> None:
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
                s.add(ServerConfig(server_id=guild.id))

    async def _build_transcript(self, thread: discord.Thread) -> str:
        lines: list[str] = []
        try:
            async for msg in thread.history(limit=1000, oldest_first=True):
                stamp = msg.created_at.strftime("%Y-%m-%d %H:%M")
                author = f"{msg.author} ({msg.author.id})"
                content = msg.content or ""
                if msg.attachments:
                    content += " " + " ".join(a.url for a in msg.attachments)
                lines.append(f"[{stamp}] {author}: {content}")
        except discord.HTTPException as exc:
            lines.append(f"<failed to read history: {exc}>")
        return "\n".join(lines)

    # ------------------------------------------------------------- commands

    @app_commands.command(name="ticket-panel", description="Send the ticket-creation panel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def ticket_panel(self, interaction: discord.Interaction) -> None:
        if interaction.channel is None:
            await interaction.response.send_message("Channel only", ephemeral=True)
            return
        embed = info_embed(
            "Need help?",
            "Click the button below to open a private support thread.",
        )
        embed.set_footer(text=FOOTER_TEXT)
        await interaction.channel.send(embed=embed, view=TicketOpenView())  # type: ignore[union-attr]
        await interaction.response.send_message("Panel posted.", ephemeral=True)

    async def create_ticket(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or interaction.channel is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return
        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("Use in a text channel", ephemeral=True)
            return

        await self._ensure_server(interaction.guild)

        async with db_session() as s:
            cfg = await s.scalar(
                select(ServerConfig).where(ServerConfig.server_id == interaction.guild.id)
            )
            support_role_ids: list[int] = list(cfg.ticket_support_role_ids) if cfg else []
            category_id: int | None = cfg.ticket_category_id if cfg else None

        guild = interaction.guild

        # Try to create a TextChannel inside the configured category. This
        # allows explicit permission overwrites (BUG #1 fix: ticket opener
        # gets explicit send/read/attach/embed permissions).
        category: discord.CategoryChannel | None = None
        if category_id:
            ch = guild.get_channel(category_id)
            if isinstance(ch, discord.CategoryChannel):
                category = ch

        if category is not None:
            try:
                overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    interaction.user: discord.PermissionOverwrite(
                        view_channel=True,
                        read_messages=True,
                        send_messages=True,
                        attach_files=True,
                        embed_links=True,
                        read_message_history=True,
                    ),
                }
                if guild.me is not None:
                    overwrites[guild.me] = discord.PermissionOverwrite(
                        view_channel=True,
                        send_messages=True,
                        manage_channels=True,
                        manage_messages=True,
                        read_message_history=True,
                        embed_links=True,
                        attach_files=True,
                    )
                for rid in support_role_ids:
                    role = guild.get_role(rid)
                    if role is not None:
                        overwrites[role] = discord.PermissionOverwrite(
                            view_channel=True,
                            send_messages=True,
                            attach_files=True,
                            embed_links=True,
                            read_message_history=True,
                            manage_messages=True,
                        )
                channel = await guild.create_text_channel(
                    name=f"ticket-{interaction.user.name}-{uuid.uuid4().hex[:6]}",
                    category=category,
                    overwrites=overwrites,
                    reason=f"Ticket opened by {interaction.user}",
                    topic=f"Ticket for {interaction.user} ({interaction.user.id})",
                )
            except discord.Forbidden:
                await interaction.response.send_message(
                    embed=err_embed(
                        "Cannot open ticket",
                        "I am missing permissions to create channels in the configured ticket category.",
                    ),
                    ephemeral=True,
                )
                return
            except discord.HTTPException as exc:
                await interaction.response.send_message(
                    embed=err_embed("Cannot open ticket", str(exc)), ephemeral=True
                )
                return

            try:
                async with db_session() as s:
                    t = Ticket(
                        server_id=guild.id,
                        opener_id=interaction.user.id,
                        thread_id=channel.id,
                        channel_id=channel.id,
                        title=f"Ticket from {interaction.user.name}",
                        last_activity_at=datetime.now(tz=timezone.utc),
                    )
                    s.add(t)
                    await s.flush()
                    ticket_id = str(t.id)
            except Exception as exc:  # noqa: BLE001
                log.warning("ticket_persist_failed", error=str(exc))
                ticket_id = "(not persisted)"

            role_mentions = " ".join(f"<@&{rid}>" for rid in support_role_ids)
            embed = info_embed(
                "Ticket opened",
                f"Hi {interaction.user.mention}, support has been notified.\n"
                f"Use the buttons below to manage this ticket.\n\nID: `{ticket_id}`",
            )
            embed.set_footer(text=FOOTER_TEXT)
            await channel.send(
                content=role_mentions or None,
                allowed_mentions=discord.AllowedMentions(roles=True),
                embed=embed,
                view=TicketControlView(),
            )
            await interaction.response.send_message(
                f"Ticket opened: {channel.mention}", ephemeral=True
            )
            return

        # Fallback: private thread (legacy behaviour)
        try:
            thread = await interaction.channel.create_thread(
                name=f"ticket-{interaction.user.name}-{uuid.uuid4().hex[:6]}",
                type=discord.ChannelType.private_thread,
                invitable=False,
                reason=f"Ticket opened by {interaction.user}",
            )
            await thread.add_user(interaction.user)
        except discord.Forbidden:
            await interaction.response.send_message(
                embed=err_embed(
                    "Cannot open ticket",
                    "I am missing permissions to create private threads in this channel.",
                ),
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            await interaction.response.send_message(
                embed=err_embed("Cannot open ticket", str(exc)), ephemeral=True
            )
            return

        try:
            async with db_session() as s:
                t = Ticket(
                    server_id=interaction.guild.id,
                    opener_id=interaction.user.id,
                    thread_id=thread.id,
                    channel_id=interaction.channel.id,
                    title=f"Ticket from {interaction.user.name}",
                    last_activity_at=datetime.now(tz=timezone.utc),
                )
                s.add(t)
                await s.flush()
                ticket_id = str(t.id)
        except Exception as exc:  # noqa: BLE001
            log.warning("ticket_persist_failed", error=str(exc))
            ticket_id = "(not persisted)"

        role_mentions = " ".join(f"<@&{rid}>" for rid in support_role_ids)
        embed = info_embed(
            "Ticket opened",
            f"Hi {interaction.user.mention}, support has been notified.\n"
            f"Use the buttons below to manage this ticket.\n\nID: `{ticket_id}`",
        )
        embed.set_footer(text=FOOTER_TEXT)
        await thread.send(
            content=role_mentions or None,
            allowed_mentions=discord.AllowedMentions(roles=True),
            embed=embed,
            view=TicketControlView(),
        )
        await interaction.response.send_message(
            f"Ticket opened: {thread.mention}", ephemeral=True
        )

    @app_commands.command(name="ticket-close", description="Close the current ticket")
    async def ticket_close(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Run inside a ticket thread", ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=ok_embed("Closing ticket", "Archiving and deleting the thread\u2026"),
            ephemeral=True,
        )
        await self._archive_and_delete(
            interaction.channel, closed_by=interaction.user.id, reason="manual close"
        )

    # ------------------------------------------------------------- panel actions

    async def _handle_close_button(self, interaction: discord.Interaction) -> None:
        thread = interaction.channel
        if not isinstance(thread, discord.Thread):
            await interaction.response.send_message(
                "Only usable inside a ticket thread.", ephemeral=True
            )
            return
        # IMPORTANT: respond FIRST, then mutate the thread. Editing the thread
        # to archived=True invalidates the interaction token and any subsequent
        # send_message returns 403 "Thread is archived".
        try:
            await interaction.response.send_message(
                embed=ok_embed(
                    "Ticket closed",
                    f"Closed by {interaction.user.mention}. Archiving the thread\u2026",
                )
            )
        except discord.InteractionResponded:
            pass
        except discord.HTTPException as exc:
            log.warning("ticket_close_response_failed", error=str(exc))

        await self._archive_and_delete(
            thread, closed_by=interaction.user.id, reason="closed via panel"
        )

    async def _handle_claim(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Only usable inside a ticket thread.", ephemeral=True
            )
            return
        try:
            if not interaction.channel.name.startswith("\N{RAISED HAND}"):
                new_name = f"\N{RAISED HAND} {interaction.channel.name}"[:100]
                await interaction.channel.edit(name=new_name)
        except discord.HTTPException:
            pass
        await interaction.response.send_message(
            embed=ok_embed(
                "Claimed", f"{interaction.user.mention} is handling this ticket."
            ),
        )

    async def _handle_transcript(self, interaction: discord.Interaction) -> None:
        if not isinstance(interaction.channel, discord.Thread):
            await interaction.response.send_message(
                "Only usable inside a ticket thread.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        text = await self._build_transcript(interaction.channel) or "(empty)"
        data = text.encode("utf-8")
        if len(data) > 7_500_000:
            data = data[-7_500_000:]
        file = discord.File(
            fp=io.BytesIO(data),
            filename=f"transcript-{interaction.channel.id}.txt",
        )
        await interaction.followup.send(
            content="Transcript attached.", file=file, ephemeral=True
        )

    # ------------------------------------------------------------- listeners

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.Thread):
            return
        try:
            async with db_session() as s:
                t = await s.scalar(
                    select(Ticket).where(Ticket.thread_id == message.channel.id)
                )
                if t is None or t.status != TicketStatus.OPEN:
                    return
                t.last_activity_at = datetime.now(tz=timezone.utc)
                s.add(
                    TicketMessage(
                        ticket_id=t.id,
                        discord_message_id=message.id,
                        author_id=message.author.id,
                        content=message.content[:4000],
                    )
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("ticket_message_persist_failed", error=str(exc))

    # ------------------------------------------------------------- close pipeline

    async def _archive_and_delete(
        self,
        thread: discord.Thread,
        *,
        closed_by: int,
        reason: str = "",
    ) -> None:
        """Persist transcript -> mark archived -> hide -> delete thread."""

        transcript = await self._build_transcript(thread)

        try:
            async with db_session() as s:
                t = await s.scalar(
                    select(Ticket).where(Ticket.thread_id == thread.id)
                )
                if t is not None:
                    t.status = TicketStatus.ARCHIVED
                    t.closed_at = datetime.now(tz=timezone.utc)
                    t.closed_by = closed_by
                    s.add(
                        TicketMessage(
                            ticket_id=t.id,
                            discord_message_id=0,
                            author_id=0,
                            content=("[transcript]\n" + transcript)[:65000],
                        )
                    )
        except Exception as exc:  # noqa: BLE001
            log.warning("ticket_archive_persist_failed", error=str(exc))

        # Try the simple, definitive path first: just delete the thread.
        # That's what users actually want.
        try:
            await thread.delete(reason=reason or "ticket closed")
            log.info("ticket_thread_deleted", thread_id=thread.id)
            return
        except discord.Forbidden as exc:
            log.warning(
                "ticket_thread_delete_forbidden",
                thread_id=thread.id,
                error=str(exc),
                hint="Bot needs Manage Threads permission on the parent channel.",
            )
        except discord.NotFound:
            return  # already gone
        except discord.HTTPException as exc:
            log.warning("ticket_thread_delete_failed", thread_id=thread.id, error=str(exc))

        # Fallback: lock + archive so the thread is at least closed off.
        try:
            await thread.edit(locked=True, archived=True, reason=reason or "ticket closed")
        except discord.HTTPException as exc:
            log.warning("ticket_thread_archive_failed", thread_id=thread.id, error=str(exc))

    async def _ipc_close(self, payload: dict[str, Any]) -> dict[str, Any]:
        ticket_id = payload.get("ticket_id")
        if not ticket_id:
            return {"status": "error", "error": "ticket_id required"}
        async with db_session() as s:
            t = await s.get(Ticket, uuid.UUID(ticket_id))
            if t is None:
                return {"status": "error", "error": "not found"}
            try:
                thread = self.bot.get_channel(t.thread_id) or await self.bot.fetch_channel(
                    t.thread_id
                )
            except discord.NotFound:
                t.status = TicketStatus.ARCHIVED
                t.closed_at = datetime.now(tz=timezone.utc)
                t.closed_by = 0
                return {"status": "ok"}
        if isinstance(thread, discord.Thread):
            await self._archive_and_delete(thread, closed_by=0, reason="closed via dashboard")
        return {"status": "ok"}


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Tickets(bot))
