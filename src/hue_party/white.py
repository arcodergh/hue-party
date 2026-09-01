"""Coarse ambient cues for white bulbs outside the entertainment area."""

import logging
import time
from collections.abc import Callable
from typing import Protocol

from hue_party.models import WhiteCue

log = logging.getLogger(__name__)


class WhiteBackend(Protocol):
    async def set_state(
        self,
        id: str,
        *,
        on: bool | None = None,
        brightness: float | None = None,
        transition_time: int | None = None,
    ) -> None: ...


class WhiteLights:
    def __init__(
        self,
        backend: WhiteBackend,
        light_ids: list[str],
        min_interval_s: float = 0.5,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._backend = backend
        self._ids = light_ids
        self._min_interval_s = min_interval_s
        self._clock = clock
        self._last_sent = -min_interval_s

    async def apply(self, cue: WhiteCue) -> None:
        now = self._clock()
        if now - self._last_sent < self._min_interval_s:
            return
        self._last_sent = now
        brightness = min(100.0, max(1.0, cue.brightness))
        failures = 0
        for light_id in self._ids:
            try:
                await self._backend.set_state(
                    light_id, on=True, brightness=brightness, transition_time=cue.transition_ms
                )
            except Exception:
                failures += 1
                log.warning("white bulb %s update failed", light_id, exc_info=True)
        if failures:
            log.info("white cue applied with %d/%d failures", failures, len(self._ids))
