"""Native voice audio player (yt-dlp + FFmpeg, no Lavalink).

One :class:`GuildPlayer` per guild keeps a queue, a currently-playing track,
volume, loop mode, and exposes pause/resume/skip/stop helpers.

This module deliberately makes no DB calls — persistence (playlists, now-
playing state for the web UI) is layered on top.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Any

import discord

from bot.config.logging import get_logger

log = get_logger("bot.audio")

try:
    import yt_dlp  # type: ignore[import-not-found]
    _YTDLP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _YTDLP_AVAILABLE = False


# Simple in-process metadata cache (TTL 1h) — saves repeated yt-dlp calls
_META_CACHE: dict[str, tuple[float, list["Track"]]] = {}
_META_TTL = 3600.0
_META_MAX = 256

# Stream URL cache (shorter TTL — signed URLs expire)
_STREAM_CACHE: dict[str, tuple[float, str]] = {}
_STREAM_TTL = 1800.0  # 30 minutes
_STREAM_MAX = 128

# Concurrency limiter for yt-dlp extractions
_EXTRACT_SEMAPHORE = asyncio.Semaphore(3)

# EQ presets — FFmpeg audio filter strings
EQ_PRESETS: dict[str, str] = {
    "flat": "",
    "bass_boost": "bass=gain=8",
    "nightcore": "asetrate=44100*1.25,aresample=44100,atempo=1.0",
    "vaporwave": "asetrate=44100*0.85,aresample=44100,atempo=1.0",
    "vocal": "highpass=f=200,lowpass=f=4000",
}


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


async def search_tracks(query: str, *, requested_by: int | None = None, limit: int = 1,
                        use_cache: bool = True) -> list[Track]:
    """Resolve ``query`` to a list of Tracks. Runs yt-dlp in an executor.

    Results for non-search queries (URLs) are cached for 1h to avoid repeated
    yt-dlp invocations on stream-URL refresh.
    """
    if not _YTDLP_AVAILABLE:
        raise RuntimeError("yt-dlp is not installed")

    cache_key = f"{query}|{limit}"
    now = time.time()
    if use_cache:
        hit = _META_CACHE.get(cache_key)
        if hit and (now - hit[0]) < _META_TTL:
            return [
                Track(**{**t.__dict__, "requested_by": requested_by})
                for t in hit[1]
            ]
        if len(_META_CACHE) > _META_MAX:
            _META_CACHE.clear()

    is_pure_search = query.startswith("ytsearch")

    def _extract() -> list[Track]:
        opts = dict(YTDL_OPTS)
        if is_pure_search:
            opts["extract_flat"] = "in_playlist"
            opts["playlistend"] = max(1, min(10, limit))
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(query, download=False)
            if info is None:
                return []
            if "entries" in info and info["entries"]:
                entries = [e for e in info["entries"] if e]
                if is_pure_search or "youtube.com/results" in (info.get("webpage_url") or ""):
                    entries = entries[:limit]
                return [Track.from_info(e, query=query, requested_by=requested_by) for e in entries]
            return [Track.from_info(info, query=query, requested_by=requested_by)]

    loop = asyncio.get_running_loop()
    async with _EXTRACT_SEMAPHORE:
        try:
            tracks = await asyncio.wait_for(
                loop.run_in_executor(None, _extract),
                timeout=15.0,
            )
        except asyncio.TimeoutError:
            log.warning("audio_search_timeout", query=query[:80])
            return []
    if use_cache and tracks:
        _META_CACHE[cache_key] = (now, list(tracks))
    return tracks


async def resolve_stream_url(query: str) -> str:
    """Resolve only the stream URL for a track, using short-lived cache."""
    now = time.time()
    cached = _STREAM_CACHE.get(query)
    if cached and (now - cached[0]) < _STREAM_TTL:
        return cached[1]

    if len(_STREAM_CACHE) > _STREAM_MAX:
        _STREAM_CACHE.clear()

    tracks = await search_tracks(query, use_cache=False, limit=1)
    if tracks and tracks[0].stream_url:
        url = tracks[0].stream_url
        _STREAM_CACHE[query] = (now, url)
        return url
    return ""


class GuildPlayer:
    """Per-guild playback state machine.

    Loop modes:
      * ``"off"``  — play queue then idle
      * ``"track"`` — repeat current track
      * ``"queue"`` — push finished track back to the end of the queue
    """

    _cleanup_interval = 60.0  # seconds between idle-guild checks
    _last_cleanup: float = 0.0

    def __init__(self, bot: discord.Client, guild_id: int) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.queue: list[Track] = []
        self.current: Track | None = None
        self.volume: float = 1.0  # 0.0 – 2.0
        self.loop: str = "off"
        self.eq_preset: str = "flat"
        self.auto_play: bool = False
        self._lock = asyncio.Lock()
        self._next_event = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._prefetch_task: asyncio.Task | None = None
        self._started_at: float = 0.0
        self._seek_offset: float = 0.0
        self._state_callbacks: list = []
        self._last_played_query: str = ""

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

    def register_state_callback(self, cb) -> None:
        self._state_callbacks.append(cb)

    def _notify_state(self) -> None:
        for cb in self._state_callbacks:
            try:
                asyncio.create_task(cb(self.snapshot()))
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    async def _player_loop(self) -> None:
        consecutive_failures = 0
        while True:
            self._next_event.clear()
            if not self.queue and self.current is None:
                # Auto-play: try to fetch related tracks
                if self.auto_play and self._last_played_query:
                    await self._try_autoplay()
                if not self.queue:
                    self._notify_state()
                    return
            if self.current is None:
                self.current = self.queue.pop(0)

            track = self.current
            self._last_played_query = track.query or track.url
            try:
                await self._play_track(track)
                consecutive_failures = 0
                self._notify_state()
            except Exception as exc:  # noqa: BLE001
                log.warning("audio_play_failed", error=str(exc), title=track.title)
                self.current = None
                consecutive_failures += 1
                # Avoid tight crash loop: if 3 in a row fail, pause briefly
                if consecutive_failures >= 3:
                    await asyncio.sleep(2.0)
                    consecutive_failures = 0
                continue

            try:
                await self._next_event.wait()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("audio_wait_failed", error=str(exc))

            # Cancel prefetch if still running
            if self._prefetch_task and not self._prefetch_task.done():
                self._prefetch_task.cancel()

            if self.loop == "track":
                continue
            if self.loop == "queue" and self.current is not None:
                self.queue.append(self.current)
            self.current = None
            self._seek_offset = 0.0
            self._notify_state()

    def _start_prefetch(self) -> None:
        """Pre-fetch the next track's stream URL to reduce gap between songs."""
        if not self.queue:
            return
        next_track = self.queue[0]
        if next_track.stream_url:
            return
        query = next_track.query or next_track.url
        if not query:
            return
        async def _do_prefetch() -> None:
            try:
                url = await resolve_stream_url(query)
                if url:
                    next_track.stream_url = url
                    log.debug("audio_prefetch_done", query=query[:60])
            except asyncio.CancelledError:
                pass
            except Exception:  # noqa: BLE001
                log.debug("audio_prefetch_failed", query=query[:60])
        self._prefetch_task = asyncio.create_task(_do_prefetch())

    async def _try_autoplay(self) -> None:
        """Fetch related tracks from YouTube when queue is empty and auto_play is on."""
        try:
            def _get_related() -> list[dict]:
                opts = dict(YTDL_OPTS)
                opts["extract_flat"] = "in_playlist"
                opts["playlistend"] = 5
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(self._last_played_query, download=False)
                    if info and "related" in info and info["related"]:
                        return info["related"][:5]
                    return []
            loop = asyncio.get_running_loop()
            related = await asyncio.wait_for(
                loop.run_in_executor(None, _get_related),
                timeout=10.0,
            )
            for entry in related:
                if entry and entry.get("url"):
                    self.add(Track(
                        query=entry.get("url", ""),
                        title=entry.get("title", "Unknown"),
                        url=entry.get("url", ""),
                        duration=int(entry.get("duration") or 0),
                        thumbnail=entry.get("thumbnail") or "",
                        uploader=entry.get("uploader") or "",
                        requested_by=self.bot.user.id if self.bot.user else None,
                    ))
            if self.queue:
                log.info("audio_autoplay_added", count=len(self.queue), guild=self.guild_id)
        except asyncio.TimeoutError:
            log.debug("audio_autoplay_timeout")
        except Exception as exc:  # noqa: BLE001
            log.debug("audio_autoplay_failed", error=str(exc))

    async def _play_track(self, track: Track) -> None:
        vc = self.voice_client
        if vc is None or not vc.is_connected():
            raise RuntimeError("Voice client not connected")

        # Use pre-fetched stream URL or resolve now
        if track.stream_url:
            cached = _STREAM_CACHE.get(track.query or track.url)
            if cached and (time.time() - cached[0]) < _STREAM_TTL:
                pass
            else:
                track.stream_url = await resolve_stream_url(track.query or track.url)
        else:
            track.stream_url = await resolve_stream_url(track.query or track.url)

        if not track.stream_url:
            raise RuntimeError("Could not resolve track stream URL")

        # Build FFmpeg options with EQ preset and seek offset
        before_opts = FFMPEG_BEFORE
        if self._seek_offset > 0:
            before_opts += f" -ss {self._seek_offset:.1f}"

        eq_filter = EQ_PRESETS.get(self.eq_preset, "")
        ffmpeg_opts = FFMPEG_OPTIONS
        if eq_filter:
            ffmpeg_opts += f" -af {eq_filter}"

        try:
            source = discord.FFmpegPCMAudio(
                track.stream_url,
                before_options=before_opts,
                options=ffmpeg_opts,
            )
            transformed = discord.PCMVolumeTransformer(source, volume=self.volume)
        except Exception as exc:  # noqa: BLE001
            log.warning("audio_ffmpeg_init_failed", error=str(exc))
            raise

        loop = asyncio.get_running_loop()
        self._started_at = loop.time()
        if self._seek_offset > 0:
            self._started_at -= self._seek_offset

        def _after(err: Exception | None) -> None:
            # Runs on the FFmpeg thread — must NOT touch asyncio state directly.
            if err is not None:
                log.warning("audio_after_error", error=str(err))
            try:
                loop.call_soon_threadsafe(self._next_event.set)
            except RuntimeError:
                # Event loop already closed; nothing to do.
                pass
            except Exception as exc:  # noqa: BLE001
                log.warning("audio_after_dispatch_failed", error=str(exc))

        try:
            vc.play(transformed, after=_after)
        except Exception as exc:  # noqa: BLE001
            log.warning("audio_play_invoke_failed", error=str(exc))
            # Make sure the loop wakes up so we move on to the next track.
            loop.call_soon_threadsafe(self._next_event.set)
            raise

        # FEAT #2: best-effort play-history recording. Never fails playback.
        try:
            asyncio.create_task(_record_play_history(self.guild_id, track))
        except Exception:  # noqa: BLE001
            pass

        # Pre-fetch next track's stream URL while current plays
        self._start_prefetch()

    # ------------------------------------------------------------------
    async def pause(self) -> None:
        vc = self.voice_client
        if vc is not None and vc.is_playing():
            vc.pause()
        self._notify_state()

    async def resume(self) -> None:
        vc = self.voice_client
        if vc is not None and vc.is_paused():
            vc.resume()
        self._notify_state()

    async def skip(self) -> None:
        vc = self.voice_client
        if vc is not None and (vc.is_playing() or vc.is_paused()):
            vc.stop()  # triggers `after` -> next_event

    async def stop(self) -> None:
        self.queue.clear()
        self.current = None
        self._seek_offset = 0.0
        vc = self.voice_client
        if vc is not None:
            try:
                vc.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                await asyncio.sleep(0.5)
            except Exception:  # noqa: BLE001
                pass
            try:
                await vc.disconnect(force=True)
            except Exception:  # noqa: BLE001
                pass
        self._next_event.set()
        self._notify_state()

    async def seek(self, seconds: float) -> None:
        """Seek to a position in the current track."""
        self._seek_offset = max(0.0, seconds)
        vc = self.voice_client
        if vc is not None and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            self._next_event.clear()
            await asyncio.sleep(0.2)
            try:
                await self._play_track(self.current)
                self._notify_state()
            except Exception as exc:  # noqa: BLE001
                log.warning("audio_seek_failed", error=str(exc))
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

    def set_eq(self, preset: str) -> None:
        """Set EQ preset. Takes effect on next track (or after seek)."""
        if preset in EQ_PRESETS:
            self.eq_preset = preset

    def position_seconds(self) -> int:
        if not self.is_playing or self._started_at == 0.0:
            return int(self._seek_offset) if self._seek_offset else 0
        try:
            loop = asyncio.get_running_loop()
            pos = loop.time() - self._started_at
            return max(0, int(pos))
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
            "eq_preset": self.eq_preset,
            "auto_play": self.auto_play,
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

    def cleanup_idle_players(self) -> int:
        """Remove players that have been idle for more than 10 minutes.

        Returns the number of removed players.
        """
        now = time.monotonic()
        if now - GuildPlayer._last_cleanup < GuildPlayer._cleanup_interval:
            return 0
        GuildPlayer._last_cleanup = now
        stale_keys: list[int] = []
        for gid, player in self._players.items():
            # Player is idle if no voice client and nothing playing
            vc = player.voice_client
            if vc is None:
                # Also check if the guild still exists on Discord
                guild = player.bot.get_guild(player.guild_id)
                if guild is None or not guild.me.voice:
                    stale_keys.append(gid)
        for gid in stale_keys:
            player = self._players.pop(gid, None)
            if player and player._task and not player._task.done():
                player._task.cancel()
            if player and player._prefetch_task and not player._prefetch_task.done():
                player._prefetch_task.cancel()
        return len(stale_keys)


_manager = AudioManager()


def get_manager() -> AudioManager:
    return _manager


def yt_dlp_available() -> bool:
    return _YTDLP_AVAILABLE


async def _record_play_history(guild_id: int, track: "Track") -> None:
    """Best-effort write to music_play_history. Errors are swallowed."""
    try:
        from bot.database.session import db_session
        from bot.database.models.music.music_play_history import MusicPlayHistory

        async with db_session() as s:
            s.add(MusicPlayHistory(
                server_id=int(guild_id),
                title=(track.title or "Unknown")[:512],
                url=(track.url or "")[:1024],
                thumbnail=(track.thumbnail or "")[:1024],
                duration=int(track.duration or 0),
                played_by=int(track.requested_by or 0),
            ))
    except Exception as exc:  # noqa: BLE001
        log.debug("music_history_write_failed", error=str(exc))


async def start_cleanup_timer(bot: discord.Client) -> None:
    """Background task that periodically cleans up idle players."""
    while not bot.is_closed():
        try:
            removed = get_manager().cleanup_idle_players()
            if removed:
                log.info("audio_cleanup_idle", removed=removed)
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(60.0)
