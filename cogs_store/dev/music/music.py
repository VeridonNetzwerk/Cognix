"""Music cog using native voice + yt-dlp + FFmpeg (no Lavalink).

Slash commands:
  /play, /pause, /resume, /skip, /stop, /queue, /nowplaying,
  /volume, /shuffle, /loop, /seek, /music-panel,
  /music dj-role, /music autoplay, /music eq, /music lyrics, /music vote-skip
  /playlist create | add | remove | play | list | delete

Playlists are persisted via :class:`MusicPlaylist`.
Per-server settings via :class:`MusicSettings`.
"""

from __future__ import annotations

COG_INFO = {
    "name": "Music",
    "description": "Music playback with playlists, EQ, auto-play, lyrics (requires yt-dlp)",
    "category": "Fun",
    "requires_admin": True,
    "version": "0.1.0",
}

EMBED_TEMPLATES = [
    {
        "key": "music_now_playing",
        "title": "Now playing",
        "description": "**{title}**\n{artist}",
        "color": 0x8B5CF6,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
    {
        "key": "music_queue",
        "title": "Music Queue",
        "description": "Up next:\n{queue}",
        "color": 0x8B5CF6,
        "footer_text": "Powered by Cognix · Made by 食べ物",
    },
]

WIDGETS = [
    {
        "id": "music_now_playing",
        "title": "Now Playing",
        "template": "widgets/music_now_playing.html",
        "size": "small",
        "icon": "ph-music-note",
    },
    {
        "id": "music_queue",
        "title": "Music Queue",
        "template": "widgets/music_queue.html",
        "size": "medium",
        "icon": "ph-queue",
    },
]

import re
import uuid
from datetime import UTC, datetime

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import select

from bot.services.audio_player import (
    EQ_PRESETS,
    Track,
    get_manager,
    search_tracks,
    yt_dlp_available,
)
from bot.utils.embeds import err_embed, info_embed, ok_embed
from bot.config.logging import get_logger
from bot.database.models.music.music_playlist import MusicPlaylist
from bot.database.models.music.music_settings import MusicSettings
from bot.database.session import db_session

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
    """Enhanced 2-row music control panel with shuffle, loop, and prev."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _player(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Guild only", ephemeral=True)
            return None
        return get_manager().get(interaction.client, interaction.guild.id)

    @discord.ui.button(label="⏮", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:prev")
    async def prev_track(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        if p.current:
            p.queue.insert(0, p.current)
        await p.skip()
        await interaction.response.send_message(embed=ok_embed("Previous"), ephemeral=True)

    @discord.ui.button(label="⏸/▶", style=discord.ButtonStyle.primary,
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

    @discord.ui.button(label="⏭", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:skip")
    async def skip_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        await p.skip()
        await interaction.response.send_message(embed=ok_embed("Skipped"), ephemeral=True)

    @discord.ui.button(label="⏹", style=discord.ButtonStyle.danger,
                       custom_id="cognix:music:stop")
    async def stop_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        await p.stop()
        await interaction.response.send_message(embed=ok_embed("Stopped"), ephemeral=True)

    @discord.ui.button(label="🔀", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:shuffle")
    async def shuffle_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        p.shuffle()
        await interaction.response.send_message(
            embed=ok_embed("Shuffled", f"{len(p.queue)} tracks"), ephemeral=True
        )

    @discord.ui.button(label="🔁", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:loop")
    async def loop_btn(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        next_mode = "off" if p.loop == "queue" else ("track" if p.loop == "off" else "queue")
        p.loop = next_mode
        await interaction.response.send_message(embed=ok_embed("Loop", next_mode), ephemeral=True)

    @discord.ui.button(label="Vol-", style=discord.ButtonStyle.secondary,
                       custom_id="cognix:music:voldown")
    async def vol_down(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        p = await self._player(interaction)
        if p is None:
            return
        p.set_volume(max(0.0, p.volume - 0.1))
        await interaction.response.send_message(
            embed=ok_embed("Volume", f"{int(p.volume * 100)}%"), ephemeral=True
        )

    @discord.ui.button(label="Vol+", style=discord.ButtonStyle.secondary,
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
# UI: search results dropdown
# ---------------------------------------------------------------------------


class TrackSelectView(discord.ui.View):
    """Dropdown for selecting a search result to play."""

    def __init__(self, tracks: list[Track], cog: "Music", user_id: int) -> None:
        super().__init__(timeout=30.0)
        self.tracks = tracks
        self.cog = cog
        self.user_id = user_id

        options = []
        for i, t in enumerate(tracks[:25]):
            label = t.title[:100]
            desc = f"{t.uploader[:50]} · {_format_duration(t.duration)}" if t.uploader else _format_duration(t.duration)
            options.append(discord.SelectOption(
                label=label,
                description=desc,
                value=str(i),
            ))

        self.select.placeholder = "Select a track to play…"
        self.select.options = options

    @discord.ui.select(cls=discord.ui.Select)
    async def select(self, interaction: discord.Interaction, select: discord.ui.Select) -> None:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Not your menu", ephemeral=True)
            return
        idx = int(select.values[0])
        track = self.tracks[idx]
        await interaction.response.defer()
        bot = interaction.client
        if interaction.guild is None:
            return
        player = get_manager().get(bot, interaction.guild.id)  # type: ignore[arg-type]
        player.add(track)
        await player.ensure_loop()
        await interaction.followup.send(
            embed=ok_embed("Queued", f"{track.title} ({_format_duration(track.duration)})")
        )
        self.stop()

    async def on_timeout(self) -> None:
        for child in self.children:
            child.disabled = True


# ---------------------------------------------------------------------------
# UI: vote skip session
# ---------------------------------------------------------------------------


class VoteSkipSession:
    """Per-guild vote skip tracking."""

    _sessions: dict[int, "VoteSkipSession"] = {}

    def __init__(self, guild_id: int) -> None:
        self.guild_id = guild_id
        self.voters: set[int] = set()
        self.created_at = datetime.now(UTC)

    @classmethod
    def get(cls, guild_id: int) -> "VoteSkipSession":
        session = cls._sessions.get(guild_id)
        if session is None:
            session = cls(guild_id)
            cls._sessions[guild_id] = session
        return session

    @classmethod
    def clear(cls, guild_id: int) -> None:
        cls._sessions.pop(guild_id, None)

    def vote(self, user_id: int) -> int:
        self.voters.add(user_id)
        return len(self.voters)

    def needed(self, vc: discord.VoiceClient) -> int:
        members = sum(1 for m in vc.channel.members if not m.bot) if vc.channel else 1
        return max(1, int(members * 0.5))

    def has_enough(self, vc: discord.VoiceClient) -> bool:
        return len(self.voters) >= self.needed(vc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_music_settings(guild_id: int) -> MusicSettings:
    """Get or create music settings for a guild."""
    async with db_session() as s:
        settings = await s.scalar(
            select(MusicSettings).where(MusicSettings.server_id == guild_id)
        )
        if settings is None:
            settings = MusicSettings(server_id=guild_id)
            s.add(settings)
        return settings


async def _is_dj(interaction: discord.Interaction) -> bool:
    """Check if user has DJ permissions for this guild."""
    if interaction.guild is None:
        return False
    if interaction.user.guild_permissions.manage_guild:
        return True
    settings = await _get_music_settings(interaction.guild.id)
    if settings.dj_role_id is None:
        return True
    if isinstance(interaction.user, discord.Member):
        return any(r.id == settings.dj_role_id for r in interaction.user.roles)
    return False


def _dj_check():
    """App command check for DJ permissions."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if not await _is_dj(interaction):
            await interaction.response.send_message(
                embed=err_embed("DJ only", "You need the DJ role or Manage Server permission to use this command."),
                ephemeral=True,
            )
            return False
        return True
    return app_commands.checks.check(predicate)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------


class Music(commands.Cog):
    """Native-voice music playback + per-server playlists + DJ roles + EQ."""

    playlist = app_commands.Group(name="playlist", description="Manage server music playlists")
    music = app_commands.Group(name="music", description="Music settings (DJ role, EQ, auto-play, etc.)")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.add_view(MusicControlView())

    async def _apply_settings(self, guild_id: int) -> None:
        """Apply per-server settings to the player."""
        settings = await _get_music_settings(guild_id)
        bot = self.bot
        guild = bot.get_guild(guild_id)
        if guild and guild.voice_client:
            player = get_manager().get_existing(guild_id)
            if player:
                player.eq_preset = settings.eq_preset
                player.auto_play = settings.auto_play
                if not player.is_playing and not player.is_paused:
                    player.set_volume(settings.default_volume / 100.0)

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
            tracks = await search_tracks(query, requested_by=interaction.user.id, limit=5)
        except Exception as exc:  # noqa: BLE001
            log.warning("music_play_search_failed", error=str(exc))
            await interaction.followup.send(embed=err_embed("Search failed", str(exc)))
            return
        if not tracks:
            await interaction.followup.send(embed=err_embed("Nothing found"))
            return

        # If multiple results and it's a search (not a URL), show dropdown
        is_url = query.startswith("http://") or query.startswith("https://")
        if len(tracks) > 1 and not is_url:
            view = TrackSelectView(tracks, self, interaction.user.id)
            await interaction.followup.send(
                embed=info_embed("Search results", f"Found {len(tracks)} tracks. Select one to play:"),
                view=view,
            )
            return

        track = tracks[0]
        player = get_manager().get(self.bot, interaction.guild.id)  # type: ignore[union-attr]
        player.add(track)
        await player.ensure_loop()
        await self._apply_settings(interaction.guild.id)  # type: ignore[union-attr]
        await interaction.followup.send(
            embed=ok_embed("Queued", f"{track.title} ({_format_duration(track.duration)})")
        )

    @app_commands.command(name="pause", description="Pause playback")
    @_dj_check()
    async def pause(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        await p.pause()
        await interaction.response.send_message(embed=ok_embed("Paused"), ephemeral=True)

    @app_commands.command(name="resume", description="Resume playback")
    @_dj_check()
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
        p = get_manager().get_existing(interaction.guild.id)
        if p is None:
            await interaction.response.send_message(embed=err_embed("Nothing playing"), ephemeral=True)
            return

        # Check vote skip
        settings = await _get_music_settings(interaction.guild.id)
        if settings.vote_skip and not await _is_dj(interaction):
            vc = interaction.guild.voice_client
            if vc and vc.channel:
                session = VoteSkipSession.get(interaction.guild.id)
                votes = session.vote(interaction.user.id)
                needed = session.needed(vc)
                if session.has_enough(vc):
                    await p.skip()
                    VoteSkipSession.clear(interaction.guild.id)
                    await interaction.response.send_message(
                        embed=ok_embed("Vote skip passed", f"{votes}/{needed} votes — skipping!"), ephemeral=True
                    )
                else:
                    await interaction.response.send_message(
                        embed=info_embed("Vote skip", f"{votes}/{needed} votes needed to skip."), ephemeral=True
                    )
                return

        await p.skip()
        await interaction.response.send_message(embed=ok_embed("Skipped"), ephemeral=True)

    @app_commands.command(name="stop", description="Stop playback and disconnect")
    @_dj_check()
    async def stop(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        await p.stop()
        VoteSkipSession.clear(interaction.guild.id)
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
        pos = p.position_seconds()
        bar_len = 20
        if t.duration > 0:
            filled = int(bar_len * pos / t.duration)
            bar = "█" * filled + "░" * (bar_len - filled)
        else:
            bar = "░" * bar_len
        embed = info_embed(
            t.title,
            f"By **{t.uploader or 'Unknown'}**\n"
            f"`{bar}` `{_format_duration(pos)} / {_format_duration(t.duration)}`\n"
            f"[Open]({t.url})",
        )
        if t.thumbnail:
            embed.set_thumbnail(url=t.thumbnail)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="volume", description="Set playback volume (0-200)")
    @_dj_check()
    async def volume(self, interaction: discord.Interaction, percent: app_commands.Range[int, 0, 200]) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        p.set_volume(percent / 100.0)
        await interaction.response.send_message(
            embed=ok_embed("Volume", f"{percent}%"), ephemeral=True
        )

    @app_commands.command(name="shuffle", description="Shuffle the queue")
    @_dj_check()
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
    @_dj_check()
    async def loop_cmd(self, interaction: discord.Interaction, mode: app_commands.Choice[str]) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get(self.bot, interaction.guild.id)
        p.loop = mode.value
        await interaction.response.send_message(
            embed=ok_embed("Loop", mode.value), ephemeral=True
        )

    @app_commands.command(name="seek", description="Seek to a position (seconds)")
    @app_commands.describe(seconds="Position in seconds to seek to")
    @_dj_check()
    async def seek_cmd(self, interaction: discord.Interaction, seconds: int) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get_existing(interaction.guild.id)
        if p is None or p.current is None:
            await interaction.response.send_message(embed=err_embed("Nothing playing"), ephemeral=True)
            return
        await p.seek(float(seconds))
        await interaction.response.send_message(
            embed=ok_embed("Seeked", f"{_format_duration(seconds)}"), ephemeral=True
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

    # ---- /music settings group ----------------------------------------

    @music.command(name="dj-role", description="Set the DJ role for music control")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_dj_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            settings = await s.scalar(
                select(MusicSettings).where(MusicSettings.server_id == interaction.guild.id)
            )
            if settings is None:
                settings = MusicSettings(server_id=interaction.guild.id, dj_role_id=role.id)
                s.add(settings)
            else:
                settings.dj_role_id = role.id
        await interaction.response.send_message(
            embed=ok_embed("DJ role set", f"Only {role.mention} can control music."), ephemeral=True
        )

    @music.command(name="autoplay", description="Toggle auto-play (related tracks when queue ends)")
    @_dj_check()
    async def toggle_autoplay(self, interaction: discord.Interaction, enabled: bool) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            settings = await s.scalar(
                select(MusicSettings).where(MusicSettings.server_id == interaction.guild.id)
            )
            if settings is None:
                settings = MusicSettings(server_id=interaction.guild.id, auto_play=enabled)
                s.add(settings)
            else:
                settings.auto_play = enabled
        p = get_manager().get_existing(interaction.guild.id)
        if p:
            p.auto_play = enabled
        await interaction.response.send_message(
            embed=ok_embed("Auto-play", "Enabled" if enabled else "Disabled"), ephemeral=True
        )

    @music.command(name="eq", description="Set EQ preset")
    @app_commands.choices(preset=[
        app_commands.Choice(name=k, value=k) for k in EQ_PRESETS
    ])
    @_dj_check()
    async def set_eq(self, interaction: discord.Interaction, preset: app_commands.Choice[str]) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            settings = await s.scalar(
                select(MusicSettings).where(MusicSettings.server_id == interaction.guild.id)
            )
            if settings is None:
                settings = MusicSettings(server_id=interaction.guild.id, eq_preset=preset.value)
                s.add(settings)
            else:
                settings.eq_preset = preset.value
        p = get_manager().get_existing(interaction.guild.id)
        if p:
            p.set_eq(preset.value)
        await interaction.response.send_message(
            embed=ok_embed("EQ preset", preset.value), ephemeral=True
        )

    @music.command(name="vote-skip", description="Toggle vote skip (requires 50% of voice channel)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle_vote_skip(self, interaction: discord.Interaction, enabled: bool) -> None:
        if interaction.guild is None:
            return
        async with db_session() as s:
            settings = await s.scalar(
                select(MusicSettings).where(MusicSettings.server_id == interaction.guild.id)
            )
            if settings is None:
                settings = MusicSettings(server_id=interaction.guild.id, vote_skip=enabled)
                s.add(settings)
            else:
                settings.vote_skip = enabled
        await interaction.response.send_message(
            embed=ok_embed("Vote skip", "Enabled" if enabled else "Disabled"), ephemeral=True
        )

    @music.command(name="lyrics", description="Get lyrics for the current track")
    async def lyrics_cmd(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            return
        p = get_manager().get_existing(interaction.guild.id)
        if p is None or p.current is None:
            await interaction.response.send_message(embed=err_embed("Nothing playing"), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        import httpx
        track = p.current
        clean_title = re.sub(r'\s*[\(\[](?:Official|MV|Music Video|Audio|Lyrics)[^)\]]*[\)\]]', '', track.title or "", flags=re.IGNORECASE).strip()
        clean_artist = (track.uploader or "").replace(" - Topic", "").strip()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("https://lrclib.net/api/get",
                                        params={"artist_name": clean_artist, "track_name": clean_title})
                if resp.status_code == 200:
                    data = resp.json()
                    lyrics = data.get("plainLyrics") or "No plain lyrics available."
                    if len(lyrics) > 4096:
                        lyrics = lyrics[:4090] + "\n…"
                    embed = info_embed(f"Lyrics: {clean_title}", lyrics or "No lyrics found.")
                    await interaction.followup.send(embed=embed, ephemeral=True)
                else:
                    await interaction.followup.send(embed=err_embed("Lyrics not found"), ephemeral=True)
        except Exception as exc:  # noqa: BLE001
            await interaction.followup.send(embed=err_embed("Lyrics error", str(exc)), ephemeral=True)

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
            now = datetime.now(UTC)
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
            pl.updated_at = datetime.now(UTC)
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
            pl.updated_at = datetime.now(UTC)
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
        await self._apply_settings(interaction.guild.id)
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
