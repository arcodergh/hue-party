"""Keeps the Hue Entertainment stream tied to music playback.

The DTLS stream is one-way: if the bridge ends it (Hue app "stop"), or another
controller takes it over, our sends silently go nowhere. This watchdog polls the
bridge's view of the stream and reclaims it while music is playing — and stops
the stream after a grace period when the music stops, so lights return to normal
and the Hue app is free to run its own sync between sets.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

STREAM_LIVE = "live"
STREAM_STOPPED = "stopped (no music)"

DEFAULT_POLL_S = 5.0
DEFAULT_MUSIC_STOP_GRACE_S = 15.0


class StreamWatchdog:
    def __init__(
        self,
        *,
        player_status: Callable[[], Awaitable[str | None]],
        remote_status: Callable[[], Awaitable[tuple[str, str]]],
        reclaim: Callable[[], Awaitable[object]],
        suspend: Callable[[], Awaitable[object]],
        on_party_start: Callable[[], Awaitable[object]] | None = None,
        on_party_stop: Callable[[], Awaitable[object]] | None = None,
        stream_required: Callable[[], bool] | None = None,
        status: dict[str, str],
        poll_s: float = DEFAULT_POLL_S,
        music_stop_grace_s: float = DEFAULT_MUSIC_STOP_GRACE_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._player_status = player_status
        self._remote_status = remote_status
        self._reclaim = reclaim
        self._suspend = suspend
        self._on_party_start = on_party_start
        self._on_party_stop = on_party_stop
        self._stream_required = stream_required
        self._party_on = False
        self._status = status
        self._poll_s = poll_s
        self._grace_s = music_stop_grace_s
        self._clock = clock
        self._suspended = False
        self._last_playing = clock()  # startup counts as activity: grace runs from launch
        self._our_rid: str | None = None

    async def poll_once(self) -> None:
        playing = (await self._player_status()) == "Playing"
        if not playing and self._stream_required is not None and self._stream_required():
            playing = True  # e.g. calibration: lights must run even with music paused
        now = self._clock()
        if playing:
            self._last_playing = now
            await self._ensure_streaming()
            if not self._party_on:
                self._party_on = True
                await self._run_party_hook(self._on_party_start, "party-start")
        elif not self._suspended and now - self._last_playing >= self._grace_s:
            log.info("music stopped %.0fs ago; stopping light stream", now - self._last_playing)
            await self._suspend()
            self._suspended = True
            self._our_rid = None
            self._status["stream"] = STREAM_STOPPED
            # Fire even if this process never saw the party start: a restart mid-party
            # loses _party_on, and the hook must still clean up (restore is idempotent).
            self._party_on = False
            await self._run_party_hook(self._on_party_stop, "party-stop")

    async def stop_party(self) -> None:
        """End the party right now — stop the stream, restore lights, no grace period."""
        if not self._suspended:
            log.info("party stopped by request; stopping light stream")
            await self._suspend()
            self._suspended = True
            self._our_rid = None
            self._status["stream"] = STREAM_STOPPED
        self._party_on = False
        await self._run_party_hook(self._on_party_stop, "party-stop")

    async def _run_party_hook(
        self, hook: Callable[[], Awaitable[object]] | None, name: str
    ) -> None:
        """A blackout/restore failure must never take stream management down with it."""
        if hook is None:
            return
        try:
            await hook()
        except Exception:
            log.exception("%s hook failed; stream management continues", name)

    async def _ensure_streaming(self) -> None:
        if self._suspended:
            log.info("music resumed; restarting light stream")
            await self._reclaim()
            self._suspended = False
            self._status["stream"] = STREAM_LIVE
            return
        state, rid = await self._remote_status()
        if state != "active":
            log.warning("bridge ended the light stream (status=%r); reclaiming", state)
            await self._reclaim()
            self._our_rid = None
        elif self._our_rid is None:
            self._our_rid = rid  # first healthy poll after (re)connect: that rid is us
        elif rid != self._our_rid:
            log.warning("another controller took over the light stream; reclaiming")
            await self._reclaim()
            self._our_rid = None
        self._status["stream"] = STREAM_LIVE

    async def run(self) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                # One flaky poll (bridge HTTP blip, playerctl hiccup) must not
                # reset watchdog state or take the loop down with it.
                log.exception("stream watchdog poll failed; retrying")
            await asyncio.sleep(self._poll_s)
