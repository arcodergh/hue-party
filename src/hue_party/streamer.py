"""Fast light path: delayed frames -> Hue Entertainment DTLS stream at ~50 fps."""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from hue_entertainment import EntertainmentArea, EntertainmentSession, LightColorCommand

from hue_party.config import Secrets, Settings
from hue_party.delay import DelayBuffer
from hue_party.models import ChannelInfo, LightFrame

log = logging.getLogger(__name__)


class SessionLike(Protocol):
    def send(self, commands: list[LightColorCommand]) -> None: ...


class LightStreamer:
    """Releases delayed LightFrames onto the DTLS stream at a fixed rate.

    When multiple frames become due in one tick (offset just lowered, scheduler
    hiccup), only the newest is sent — stale colors are worthless.
    """

    def __init__(
        self,
        session: SessionLike,
        buffer: DelayBuffer,
        *,
        fps: int = 50,
        clock: Callable[[], float] = time.monotonic,
        reconnect: Callable[[], Coroutine[Any, Any, SessionLike]] | None = None,
    ) -> None:
        self._session = session
        self._buffer = buffer
        self._fps = fps
        self._clock = clock
        self._reconnect = reconnect
        self.offset_ms: int = 0

    def submit(self, frame: LightFrame) -> None:
        self._buffer.push(frame)

    def tick(self) -> bool:
        due = self._buffer.pop_due(self._clock(), self.offset_ms / 1000)
        if not due:
            return False
        frame = due[-1]
        self._session.send(
            [
                LightColorCommand(channel_id=cid, red=c.red, green=c.green, blue=c.blue)
                for cid, c in frame.channels.items()
            ]
        )
        return True

    async def reconnect_now(self) -> None:
        """Swap in a fresh session; for callers that detect stream death out-of-band."""
        if self._reconnect is None:
            raise RuntimeError("LightStreamer has no reconnect callback configured")
        self._session = await self._reconnect()

    async def run_once(self) -> None:
        try:
            self.tick()
        except Exception:
            if self._reconnect is None:
                raise
            log.exception("light stream failed; reconnecting")
            self._session = await self._reconnect()

    async def run(self) -> None:
        interval = 1 / self._fps
        while True:
            await self.run_once()
            await asyncio.sleep(interval)


def channel_infos(area: EntertainmentArea) -> list[ChannelInfo]:
    """Convert the bridge's channel list into our position-bearing ChannelInfo."""
    return [
        ChannelInfo(ch.channel_id, ch.position[0], ch.position[1], ch.position[2])
        for ch in area.channels
    ]


async def open_session(
    settings: Settings, secrets: Secrets
) -> tuple[EntertainmentSession, EntertainmentArea]:
    """Connect, resolve the configured entertainment area, and start streaming."""
    session = EntertainmentSession(
        settings.hue.bridge_host,
        secrets.hue_app_key,
        secrets.hue_client_key,
        idle_timeout=0,  # we stream continuously; never let the session self-close
    )
    try:
        areas = await session.get_entertainment_areas()
        if not areas:
            raise RuntimeError(
                "No entertainment areas on the bridge. Create one in the Hue app: "
                "Settings -> Entertainment areas."
            )
        wanted = settings.hue.entertainment_area
        area = next((a for a in areas if a.id == wanted), areas[0] if not wanted else None)
        if area is None:
            available = ", ".join(f"{a.id} ({a.name})" for a in areas)
            raise RuntimeError(f"Entertainment area '{wanted}' not found. Available: {available}")
        await session.start(area.id)
        log.info("Streaming to area '%s' with %d channels", area.name, len(area.channels))
        return session, area
    except BaseException:
        await session.aclose()
        raise
