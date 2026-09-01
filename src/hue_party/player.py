"""Play/pause/skip Chrome's YouTube Music tab through MPRIS (playerctl)."""

import asyncio
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

Runner = Callable[..., Awaitable[tuple[int, str, str]]]


class PlayerError(RuntimeError):
    pass


async def _exec(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


class PlayerControl:
    def __init__(self, runner: Runner = _exec) -> None:
        self._run = runner
        self._player: str | None = None

    async def _detect(self) -> str:
        try:
            rc, out, err = await self._run("playerctl", "-l")
        except OSError as exc:  # binary missing (e.g. dev box without playerctl)
            raise PlayerError(f"playerctl not available: {exc}") from exc
        if rc != 0:
            raise PlayerError(f"playerctl failed: {err.strip() or rc}")
        for line in out.splitlines():
            if "chrom" in line:  # chromium.instanceNNN / chrome.instanceNNN
                return line.strip()
        raise PlayerError(
            "No Chromium MPRIS player found — is YouTube Music open and playing in Chrome?"
        )

    async def _playerctl(self, *args: str) -> str:
        if self._player is None:
            self._player = await self._detect()
        try:
            rc, out, err = await self._run("playerctl", "-p", self._player, *args)
        except OSError as exc:
            raise PlayerError(f"playerctl not available: {exc}") from exc
        if rc != 0:
            self._player = None  # tab may have closed; re-detect next time
            raise PlayerError(f"playerctl {' '.join(args)} failed: {err.strip() or rc}")
        return out.strip()

    async def play_pause(self) -> None:
        await self._playerctl("play-pause")

    async def next_track(self) -> None:
        await self._playerctl("next")

    async def previous_track(self) -> None:
        await self._playerctl("previous")

    async def pause(self) -> None:
        await self._playerctl("pause")

    async def play(self) -> None:
        await self._playerctl("play")

    async def stop(self) -> None:
        """Stop playback; some players only implement pause, so fall back to it."""
        try:
            await self._playerctl("stop")
        except PlayerError:
            log.info("playerctl stop not supported; pausing instead")
            await self._playerctl("pause")

    async def status(self) -> str | None:
        """MPRIS playback status: "Playing", "Paused", "Stopped", or None if unavailable."""
        try:
            return await self._playerctl("status")
        except PlayerError:
            return None

    async def now_playing(self) -> str | None:
        try:
            return await self._playerctl("metadata", "--format", "{{artist}} — {{title}}")
        except PlayerError:
            return None

    async def art_url(self) -> str | None:
        try:
            url = await self._playerctl("metadata", "mpris:artUrl")
        except PlayerError:
            return None
        return url or None


async def poll_track(controller: object, player: object, interval_s: float = 3.0) -> None:
    """Keep controller.track fresh; import types via Protocol to avoid a cycle."""
    from hue_party.controller import PlayerLike, ShowController  # circular-import mitigation

    assert isinstance(controller, ShowController)
    p: PlayerLike = player  # type: ignore[assignment]
    while True:
        track = await p.now_playing()
        if track != controller.track:
            controller.track = track
        await asyncio.sleep(interval_s)
