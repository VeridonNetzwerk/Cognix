"""Stats cog: track messages, commands, joins/leaves."""

from __future__ import annotations

from datetime import date, datetime, timezone

import discord
from discord.ext import commands, tasks
from sqlalchemy import func, select

from config.logging import get_logger
from database import db_session
from database.models.server import Server
from database.models.stats import AggregatedStat, StatEvent, StatEventType


log = get_logger("bot.cogs.stats")


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._aggregate.start()

    def cog_unload(self) -> None:
        self._aggregate.cancel()

    async def _ensure_server(self, server_id: int | None) -> bool:
        """Make sure a Server row exists so FK insert into stat_events works.

        Returns True when the event can safely be inserted.
        """
        if server_id is None:
            return True
        async with db_session() as s:
            existing = await s.get(Server, server_id)
            if existing is not None:
                return True
            guild = self.bot.get_guild(server_id)
            if guild is None:
                return False
            s.add(Server(
                id=guild.id,
                name=guild.name,
                member_count=guild.member_count or 0,
            ))
        return True

    async def _record(
        self,
        *,
        event_type: StatEventType,
        server_id: int | None,
        user_id: int | None = None,
        name: str = "",
    ) -> None:
        if not await self._ensure_server(server_id):
            return
        try:
            async with db_session() as s:
                s.add(
                    StatEvent(
                        server_id=server_id,
                        event_type=event_type,
                        user_id=user_id,
                        name=name[:64],
                        occurred_at=datetime.now(tz=timezone.utc),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            # Never let stat recording bubble up and crash command handlers.
            log.warning("stats_record_failed", error=str(exc))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        await self._record(
            event_type=StatEventType.MESSAGE, server_id=message.guild.id, user_id=message.author.id
        )

    @commands.Cog.listener()
    async def on_app_command_completion(
        self, interaction: discord.Interaction, command: discord.app_commands.Command
    ) -> None:
        await self._record(
            event_type=StatEventType.COMMAND,
            server_id=interaction.guild_id,
            user_id=interaction.user.id,
            name=command.qualified_name,
        )

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self._record(
            event_type=StatEventType.JOIN, server_id=member.guild.id, user_id=member.id
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await self._record(
            event_type=StatEventType.LEAVE, server_id=member.guild.id, user_id=member.id
        )

    @tasks.loop(minutes=5)
    async def _aggregate(self) -> None:
        """Roll raw stat_events into aggregated_stats and prune."""
        today = date.today()
        async with db_session() as s:
            rows = (
                await s.execute(
                    select(
                        StatEvent.server_id,
                        StatEvent.event_type,
                        StatEvent.name,
                        func.count().label("c"),
                    )
                    .where(func.date(StatEvent.occurred_at) == today)
                    .group_by(StatEvent.server_id, StatEvent.event_type, StatEvent.name)
                )
            ).all()
            for sid, etype, ename, c in rows:
                existing = await s.scalar(
                    select(AggregatedStat).where(
                        AggregatedStat.day == today,
                        AggregatedStat.server_id == sid,
                        AggregatedStat.event_type == etype,
                        AggregatedStat.name == ename,
                    )
                )
                if existing is None:
                    s.add(
                        AggregatedStat(
                            day=today,
                            server_id=sid,
                            event_type=etype,
                            name=ename,
                            count=int(c),
                        )
                    )
                else:
                    existing.count = int(c)

    @_aggregate.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Stats(bot))
