"""Native voice audio player (yt-dlp + FFmpeg, no Lavalink).

One :class:`GuildPlayer` per guild keeps a queue, a currently-playing track,
volume, loop mode, and exposes pause/resume/skip/stop helpers.

This module deliberately makes no DB calls — persistence (playlists, now-
playing state for the web UI) is layered on top.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any

import discord

from config.logging import get_logger

log = get_logger("bot.audio")

try:
    import yt_dlp  # type: ignore[import-not-found]
    _YTDLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YTDLP_AVAILABLE = False


YTDL_OPTS: dict[str, Any] = {
    "format": "bestaudio/best",
    "noplaylist": False,
    "default_search": "ytsearch",
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": False,
    "source_address": "0.0.0.0",
}

FFMPEG_BEFORE = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-nostdin -loglevel warning"
)
FFMPEG_OPTIONS = "-vn"


@dataclass
class Track:
    """A resolvable audio track. ``stream_url`` is fetched lazily."""

    query: str
    title: str = "Unknown"
    url: str = ""  # canonical webpage URL
    duration: int = 0
    thumbnail: str = ""
    uploader: str = ""
    requested_by: int | None = None
    stream_url: str = ""
    extractor_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_info(cls, info: dict[str, Any], *, query: str = "", requested_by: int | None = None) -> "Track":
        return cls(
            query=query or info.get("webpage_url") or info.get("url") or "",
            title=info.get("title") or "Unknown",
            url=info.get("webpage_url") or info.get("url") or "",
            duration=int(info.get("duration") or 0),
            thumbnail=info.get("thumbnail") or "",
            uploader=info.get("uploader") or info.get("channel") or "",
            requested_by=requested_by,
            stream_url=info.get("url") or "",
            extractor_data={"id": info.get("id"), "extractor": info.get("extractor")},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "title": self.title,
            "url": self.url,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
            "uploader": self.uploader,
            "requested_by": self.requested_by,
        }


async def search_tracks(query: str, *, requested_by: int | None = None, limit: int = 1) -> list[Track]:
    """Resolve ``query`` to a list of Tracks. Runs yt-dlp in a thread."""
    if not _YTDLP_AVAILABLE:
        raise RuntimeError("yt-dlp is not installed")

    def _extract() -> list[Track]:
        with yt_dlp.YoutubeDL(YTDL_OPTS) as ydl:
            info = ydl.extract_info(query, download=False)
            if info is None:
                return []
            if "entries" in info and info["entries"]:
                # playlist or search result
                entries = [e for e in info["entries"] if e]
                if query.startswith("ytsearch") or "youtube.com/results" in (info.get("webpage_url") or ""):
                    entries = entries[:limit]
                return [Track.from_info(e, query=query, requested_by=requested_by) for e in entries]
            return [Track.from_info(info, query=query, requested_by=requested_by)]

    return await asyncio.to_thread(_extract)


class GuildPlayer:
    """Per-guild playback state machine.

    Loop modes:
      * ``"off"``  — play queue then idle
      * ``"track"`` — repeat current track
      * ``"queue"`` — push finished track back to the end of the queue
    """

    def __init__(self, bot: discord.Client, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.volume: float = 1.0  # 0.0 – 2.0
        self.loop: str = "off"
        self._lock = asyncio.Lock()
        self._next_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._started_at: float = 0.0

    # ------------------------------------------------------------------
    @property
    def voice_client(self) -> discord.VoiceClient | None:
        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            return None
        return guild.voice_client  # type: ignore[return-value]

    @property
    def is_playing(self) -> bool:
        vc = self.voice_client
        return vc is not None and vc.is_playing()

    @property
    def is_paused(self) -> bool:
        vc = self.voice_client
        return vc is not None and vc.is_paused()

    # ------------------------------------------------------------------
    async def ensure_loop(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._player_loop())

    def add(self, track: Track) -> None:
        self.queue.append(track)

    def shuffle(self) -> None:
        random.shuffle(self.queue)

    def remove(self, index: int) -> Track | None:
        if 0 <= index < len(self.queue):
            return self.queue.pop(index)
        return None

    def clear(self) -> None:
        self.queue.clear()

    # ------------------------------------------------------------------
    async def _player_loop(self) -> None:
        while True:
            self._next_event.clear()
            if not self.queue and self.current is None:
                # nothing scheduled
                return
            if self.current is None:
                self.current = self.queue.pop(0)

            track = self.current
            try:
                await self._play_track(track)
            except Exception as exc:  # noqa: BLE001
                log.warning("audio_play_failed", error=str(exc), title=track.title)
                self.current = None
                continue

            await self._next_event.wait()

            if self.loop == "track":
                continue  # replay same track
            if self.loop == "queue" and self.current is not None:
                self.queue.append(self.current)
            self.current = None

    async def _play_track(self, track: Track) -> None:
        vc = self.voice_client
        if vc is None or not vc.is_connected():
            raise RuntimeError("Voice client not connected")

        # Re-resolve the stream URL: yt-dlp signed URLs expire quickly.
        info_list = await search_tracks(track.query or track.url, requested_by=track.requested_by)
        if not info_list:
            raise RuntimeError("Could not resolve track")
        track.stream_url = info_list[0].stream_url
        if not track.thumbnail:
            track.thumbnail = info_list[0].thumbnail

        source = discord.FFmpegPCMAudio(
            track.stream_url,
            before_options=FFMPEG_BEFORE,
            options=FFMPEG_OPTIONS,
        )
        transformed = discord.PCMVolumeTransformer(source, volume=self.volume)
        loop = asyncio.get_running_loop()
        self._started_at = loop.time()

        def _after(err: Exception | None) -> None:
            if err is not None:
                log.warning("audio_after_error", error=str(err))
            loop.call_soon_threadsafe(self._next_event.set)

        vc.play(transformed, after=_after)

    # ------------------------------------------------------------------
    async def pause(self) -> None:
        vc = self.voice_client
        if vc is not None and vc.is_playing():
            vc.pause()

    async def resume(self) -> None:
        vc = self.voice_client
        if vc is not None and vc.is_paused():
            vc.resume()

    async def skip(self) -> None:
        vc = self.voice_client
        if vc is not None and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # triggers `after` -> next_event

    async def stop(self) -> None:
        self.queue.clear()
        self.current = None
        vc = self.voice_client
        if vc is not None:
            vc.stop()
            try:
                await vc.disconnect(force=True)
            except Exception:  # noqa: BLE001
                pass
        self._next_event.set()

    def set_volume(self, value: float) -> None:
        value = max(0.0, min(2.0, value))
        self.volume = value
        vc = self.voice_client
        if vc is not None and vc.source is not None:
            try:
                vc.source.volume = value  # type: ignore[attr-defined]
            except Exception:  # noqa: BLE001
                pass

    def position_seconds(self) -> int:
        if not self.is_playing or self._started_at == 0.0:
            return 0
        try:
            loop = asyncio.get_running_loop()
            return int(loop.time() - self._started_at)
        except RuntimeError:
            return 0

    def snapshot(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "current": self.current.to_dict() if self.current else None,
            "queue": [t.to_dict() for t in self.queue],
            "volume": self.volume,
            "loop": self.loop,
            "is_playing": self.is_playing,
            "is_paused": self.is_paused,
            "position": self.position_seconds(),
        }


class AudioManager:
    """Registry of per-guild players. Singleton via :func:`get_manager`."""

    def __init__(self) -> None:
        self._players: dict[int, GuildPlayer] = {}

    def get(self, bot: discord.Client, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(bot, guild_id)
            self._players[guild_id] = player
        return player

    def get_existing(self, guild_id: int) -> GuildPlayer | None:
        return self._players.get(guild_id)

    def all(self) -> dict[int, GuildPlayer]:
        return dict(self._players)


_manager = AudioManager()


def get_manager() -> AudioManager:
    return _manager


def yt_dlp_available() -> bool:
    return _YTDLP_AVAILABLE
