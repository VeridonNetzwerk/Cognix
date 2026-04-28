"""Music cog using native voice + yt-dlp + FFmpeg (no Lavalink).

Slash commands:
  /play, /pause, /resume, /skip, /stop, /queue, /nowplaying,
  /volume, /shuffle, /loop, /music-panel,
  /playlist create | add | remove | play | list | delete

Playlists are persisted via :class:`MusicPlaylist`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.services.audio_player import (
    Track,
    get_manager,
    search_tracks,
    yt_dlp_available,
)
from bot.utils.embeds import err_embed, info_embed, ok_embed
from config.logging import get_logger
from database.models.music_playlist import MusicPlaylist
from database.session import db_session

log = get_logger("bot.cogs.music")


def _format_duration(seconds: int) -> str:
    if not seconds:
        return "live"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _unavailable_embed() -> discord.Embed:
    return err_embed(
        "Music unavailable",
        "yt-dlp is not installed in the bot environment. Install `yt-dlp` "
        "and ensure FFmpeg is available on PATH, then restart.",
    )


# ---------------------------------------------------------------------------
# UI: persistent control panel
# ---------------------------------------------------------------------------


class MusicControlView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _player(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return None
        return get_manager().get(interaction.client, interaction.guild.id)

    @discord.ui.button(label="Pause/Resume", style=discord.ButtonStyle.primary,
                       custom_id="cognix:music:pauseresume")
    async def pause_resume(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        if p.is_paused:
            await p.resume()
            await interaction.response.send_message(embed=ok_embed("Resumed"), ephemeral=True)
        else:
            await p.pause()
            await interaction.response.send_message(embed=ok_embed("Paused"), ephemeral=True)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:skip")
    async def skip(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        await p.skip()
        await interaction.response.send_message(embed=ok_embed("Skipped"), ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger,
                       custom_id="cognix:music:stop")
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        await p.stop()
        await interaction.response.send_message(embed=ok_embed("Stopped"), ephemeral=True)

    @discord.ui.button(label="Vol -", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:voldown")
    async def vol_down(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        p.set_volume(max(0.0, p.volume - 0.1))
        await interaction.response.send_message(
            embed=ok_embed("Volume", f"{int(p.volume * 100)}%"), ephemeral=True
        )

    @discord.ui.button(label="Vol +", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:volup")
    async def vol_up(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        p.set_volume(min(2.0, p.volume + 0.1))
        await interaction.response.send_message(
            embed=ok_embed("Volume", f"{int(p.volume * 100)}%"), ephemeral=True
        )


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class Music(commands.Cog):
    """Native-voice music playback + per-server playlists."""

    playlist = app_commands.Group(name="playlist", description="Manage server music playlists")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(MusicControlView())

    # ---- helpers ------------------------------------------------------

    async def _ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient | None:
        """Connect to the user's voice channel if not yet connected."""
        if not isinstance(interaction.user, discord.Member) or interaction.user.voice is None:
            await interaction.followup.send(
                embed=err_embed("Join a voice channel first"), ephemeral=True
            )
            return None
        channel = interaction.user.voice.channel
        if interaction.guild is None or channel is None:
            return None
        vc = interaction.guild.voice_client
        if vc is None:
            try:
                vc = await channel.connect()
            except Exception as exc:  # noqa: BLE001
                await interaction.followup.send(
                    embed=err_embed("Connect failed", str(exc)), ephemeral=True
                )
                return None
        elif vc.channel != channel:
            try:
                await vc.move_to(channel)
            except Exception:  # noqa: BLE001
                pass
        return vc  # type: ignore[return-value]

    # ---- /play --------------------------------------------------------

    @app_commands.command(name="play", description="Play a URL or search query")
    @app_commands.describe(query="URL or search keywords")
    async def play(self, interaction: discord.Interaction, query: str) -> None:
        if not yt_dlp_available():
            await interaction.response.send_message(embed=_unavailable_embed(), ephemeral=True)
            return
        await interaction.response.defer()
        vc = await self._ensure_voice(interaction)
        if vc is None:
            return
        try:
            tracks = await search_tracks(query, requested_by=interaction.user.id, limit=1)
        except Exception as exc:  # noqa: BLE001
            log.warning("music_play_search_failed", error=str(exc))
            await interaction.followup.send(embed=err_embed("Search failed", str(exc)))
            return
        if not tracks:
            await interaction.followup.send(embed=err_embed("Nothing found"))
            return
        player = get_manager().get(self.bot, interaction.guild.id)  # type: ignore[union-attr]
        for t in tracks:
            player.add(t)
        await player.ensure_loop()
        if len(tracks) == 1:
            await interaction.followup.send(
                embed=ok_embed("Queued", f"{tracks[0].title} ({_format_duration(tracks[0].duration)})")
            )
        else:
            await interaction.followup.send(
                embed=ok_embed("Queued", f"{len(tracks)} tracks")
            )

    @app_commands.command(name="pause", description="Pause playback")
    async def pause(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        await p.pause()
        await interaction.response.send_message(embed=ok_embed("Paused"), ephemeral=True)

    @app_commands.command(name="resume", description="Resume playback")
    async def resume(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        await p.resume()
        await interaction.response.send_message(embed=ok_embed("Resumed"), ephemeral=True)

    @app_commands.command(name="skip", description="Skip the current track")
    async def skip(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        await p.skip()
        await interaction.response.send_message(embed=ok_embed("Skipped"), ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and disconnect")
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        await p.stop()
        await interaction.response.send_message(embed=ok_embed("Stopped"), ephemeral=True)

    @app_commands.command(name="queue", description="Show the current queue")
    async def queue_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get_existing(interaction.guild.id)
        if p is None or (p.current is None and not p.queue):
            await interaction.response.send_message(
                embed=info_embed("Queue is empty"), ephemeral=True
            )
            return
        lines: list[str] = []
        if p.current:
            lines.append(f"**Now:** {p.current.title} ({_format_duration(p.current.duration)})")
        for i, t in enumerate(p.queue[:15], 1):
            lines.append(f"`{i}.` {t.title} ({_format_duration(t.duration)})")
        await interaction.response.send_message(
            embed=ok_embed("Queue", "\n".join(lines)), ephemeral=True
        )

    @app_commands.command(name="nowplaying", description="Show what's currently playing")
    async def nowplaying(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get_existing(interaction.guild.id)
        if p is None or p.current is None:
            await interaction.response.send_message(
                embed=info_embed("Nothing is playing"), ephemeral=True
            )
            return
        t = p.current
        embed = info_embed(
            t.title,
            f"By **{t.uploader or 'Unknown'}**\n"
            f"`{_format_duration(p.position_seconds())} / {_format_duration(t.duration)}`\n"
            f"[Open]({t.url})",
        )
        if t.thumbnail:
            embed.set_thumbnail(url=t.thumbnail)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="volume", description="Set playback volume (0-200)")
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 0, 200]) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        p.set_volume(percent / 100.0)
        await interaction.response.send_message(
            embed=ok_embed("Volume", f"{percent}%"), ephemeral=True
        )

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    async def shuffle_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        p.shuffle()
        await interaction.response.send_message(
            embed=ok_embed("Shuffled", f"{len(p.queue)} tracks"), ephemeral=True
        )

    @app_commands.command(name="loop", description="Set loop mode")
    @app_commands.choices(
        mode=[
            app_commands.Choice(name="off", value="off"),
            app_commands.Choice(name="track", value="track"),
            app_commands.Choice(name="queue", value="queue"),
        ]
    )
    async def loop_cmd(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        p.loop = mode.value
        await interaction.response.send_message(
            embed=ok_embed("Loop", mode.value), ephemeral=True
        )

    @app_commands.command(name="music-panel", description="Send the music control panel")
    @app_commands.checks.has_permissions(manage_channels=True)
    async def music_panel(self, interaction: discord.Interaction) -> None:
        if interaction.channel is None:
            return
        embed = info_embed(
            "🎵 Music Controls",
            "Use the buttons below to control playback. Start with `/play <query>`.",
        )
        await interaction.channel.send(embed=embed, view=MusicControlView())  # type: ignore[union-attr]
        await interaction.response.send_message("Music panel posted.", ephemeral=True)

    # ---- /playlist ----------------------------------------------------

    async def _playlist_name_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        async with db_session() as s:
            rows = (
                await s.scalars(
                    select(MusicPlaylist).where(MusicPlaylist.server_id == interaction.guild.id)
                )
            ).all()
        out: list[app_commands.Choice[str]] = []
        cur = (current or "").lower()
        for r in rows:
            if cur and cur not in r.name.lower():
                continue
            out.append(app_commands.Choice(name=f"{r.name} ({len(r.tracks)})", value=r.name))
            if len(out) >= 25:
                break
        return out

    @playlist.command(name="create", description="Create a new playlist")
    async def pl_create(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            existing = await s.scalar(
                select(MusicPlaylist).where(
                    MusicPlaylist.server_id == interaction.guild.id,
                    MusicPlaylist.name == name,
                )
            )
            if existing is not None:
                await interaction.response.send_message(
                    embed=err_embed("Already exists"), ephemeral=True
                )
                return
            now = datetime.now(tz=timezone.utc)
            s.add(
                MusicPlaylist(
                    id=uuid.uuid4(),
                    server_id=interaction.guild.id,
                    name=name,
                    created_by=interaction.user.id,
                    tracks=[],
                    created_at=now,
                    updated_at=now,
                )
            )
        await interaction.response.send_message(
            embed=ok_embed("Playlist created", name), ephemeral=True
        )

    @playlist.command(name="add", description="Add a track to a playlist")
    @app_commands.autocomplete(name=_playlist_name_autocomplete)
    async def pl_add(self, interaction: discord.Interaction, name: str, url: str) -> None:
        if interaction.guild is None:
            return
        if not yt_dlp_available():
            await interaction.response.send_message(embed=_unavailable_embed(), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            tracks = await search_tracks(url, requested_by=interaction.user.id, limit=1)
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(embed=err_embed("Resolve failed", str(exc)))
            return
        if not tracks:
            await interaction.followup.send(embed=err_embed("Nothing found"))
            return
        async with db_session() as s:
            pl = await s.scalar(
                select(MusicPlaylist).where(
                    MusicPlaylist.server_id == interaction.guild.id,
                    MusicPlaylist.name == name,
                )
            )
            if pl is None:
                await interaction.followup.send(embed=err_embed("Playlist not found"))
                return
            pl.tracks = list(pl.tracks) + [tracks[0].to_dict()]
            pl.updated_at = datetime.now(tz=timezone.utc)
        await interaction.followup.send(
            embed=ok_embed("Added", f"{tracks[0].title} → {name}")
        )

    @playlist.command(name="remove", description="Remove a track by index from a playlist")
    @app_commands.autocomplete(name=_playlist_name_autocomplete)
    async def pl_remove(self, interaction: discord.Interaction, name: str, index: int) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            pl = await s.scalar(
                select(MusicPlaylist).where(
                    MusicPlaylist.server_id == interaction.guild.id,
                    MusicPlaylist.name == name,
                )
            )
            if pl is None:
                await interaction.response.send_message(
                    embed=err_embed("Playlist not found"), ephemeral=True
                )
                return
            tracks = list(pl.tracks)
            if not 1 <= index <= len(tracks):
                await interaction.response.send_message(
                    embed=err_embed("Index out of range"), ephemeral=True
                )
                return
            removed = tracks.pop(index - 1)
            pl.tracks = tracks
            pl.updated_at = datetime.now(tz=timezone.utc)
        await interaction.response.send_message(
            embed=ok_embed("Removed", removed.get("title", "?")), ephemeral=True
        )

    @playlist.command(name="play", description="Queue all tracks from a playlist")
    @app_commands.autocomplete(name=_playlist_name_autocomplete)
    async def pl_play(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None:
            return
        if not yt_dlp_available():
            await interaction.response.send_message(embed=_unavailable_embed(), ephemeral=True)
            return
        await interaction.response.defer()
        async with db_session() as s:
            pl = await s.scalar(
                select(MusicPlaylist).where(
                    MusicPlaylist.server_id == interaction.guild.id,
                    MusicPlaylist.name == name,
                )
            )
            if pl is None:
                await interaction.followup.send(embed=err_embed("Playlist not found"))
                return
            track_data = list(pl.tracks)
        if not track_data:
            await interaction.followup.send(embed=info_embed("Playlist is empty"))
            return
        vc = await self._ensure_voice(interaction)
        if vc is None:
            return
        player = get_manager().get(self.bot, interaction.guild.id)
        for raw in track_data:
            player.add(
                Track(
                    query=raw.get("query") or raw.get("url") or "",
                    title=raw.get("title") or "Unknown",
                    url=raw.get("url") or "",
                    duration=int(raw.get("duration") or 0),
                    thumbnail=raw.get("thumbnail") or "",
                    uploader=raw.get("uploader") or "",
                    requested_by=interaction.user.id,
                )
            )
        await player.ensure_loop()
        await interaction.followup.send(
            embed=ok_embed("Queued playlist", f"{name} ({len(track_data)} tracks)")
        )

    @playlist.command(name="list", description="List server playlists")
    async def pl_list(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            rows = (
                await s.scalars(
                    select(MusicPlaylist).where(MusicPlaylist.server_id == interaction.guild.id)
                )
            ).all()
        if not rows:
            await interaction.response.send_message(
                embed=info_embed("No playlists yet"), ephemeral=True
            )
            return
        lines = [f"• **{r.name}** — {len(r.tracks)} tracks" for r in rows]
        await interaction.response.send_message(
            embed=ok_embed("Playlists", "\n".join(lines)), ephemeral=True
        )

    @playlist.command(name="delete", description="Delete a playlist")
    @app_commands.autocomplete(name=_playlist_name_autocomplete)
    async def pl_delete(self, interaction: discord.Interaction, name: str) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            pl = await s.scalar(
                select(MusicPlaylist).where(
                    MusicPlaylist.server_id == interaction.guild.id,
                    MusicPlaylist.name == name,
                )
            )
            if pl is None:
                await interaction.response.send_message(
                    embed=err_embed("Not found"), ephemeral=True
                )
                return
            await s.delete(pl)
        await interaction.response.send_message(
            embed=ok_embed("Deleted", name), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Music(bot))
