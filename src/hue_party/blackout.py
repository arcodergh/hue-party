"""Party blackout: turn every non-party light off while the show runs, restore after.

The pre-party snapshot is persisted to disk before any light is touched, so a crash
mid-party cannot lose the real pre-party state: an existing snapshot file is treated
as the older truth and reused instead of re-snapshotting lights that are already off.
"""

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

OFF_TRANSITION_MS = 800
ON_TRANSITION_MS = 1200
DEFAULT_SNAPSHOT_PATH = Path("~/.config/hue-party/blackout.json")


class _LightLike(Protocol):
    id: str
    on: object  # aiohue OnFeature: .on bool
    dimming: object | None  # aiohue DimmingFeature: .brightness float


class LightsBackend(Protocol):
    """The slice of aiohue's LightsController that blackout needs."""

    def __iter__(self) -> Iterator[_LightLike]: ...

    async def set_state(
        self,
        id: str,
        *,
        on: bool | None = None,
        brightness: float | None = None,
        color_temp: int | None = None,
        transition_time: int | None = None,
    ) -> None: ...


class Blackout:
    def __init__(
        self, lights: LightsBackend, *, exclude_ids: set[str], snapshot_path: Path
    ) -> None:
        self._lights = lights
        self._exclude = exclude_ids
        self._path = snapshot_path
        self._snapshot: dict[str, float | None] | None = None

    @property
    def active(self) -> bool:
        """True while other lights are held off (callers should skip white cues)."""
        return self._snapshot is not None

    async def activate(self) -> None:
        """Snapshot every other light that is on, persist it, then turn them off."""
        if self._snapshot is not None:
            return
        if self._path.exists():
            # Crash mid-party: the file holds the true pre-party state; keep it.
            self._snapshot = json.loads(self._path.read_text())["lights"]
            log.warning("reusing pre-party light snapshot left behind at %s", self._path)
        else:
            self._snapshot = {
                light.id: getattr(light.dimming, "brightness", None)
                for light in self._lights
                if light.id not in self._exclude and getattr(light.on, "on", False)
            }
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"lights": self._snapshot}))
        failures = 0
        for light in self._lights:
            if light.id in self._exclude or not getattr(light.on, "on", False):
                continue
            try:
                await self._lights.set_state(light.id, on=False, transition_time=OFF_TRANSITION_MS)
            except Exception:
                failures += 1
                log.warning("could not turn off light %s for the party", light.id, exc_info=True)
        log.info("party blackout on: %d lights off (%d failures)", len(self._snapshot), failures)

    async def restore(self) -> None:
        """Bring the snapshotted lights back to their pre-party on/brightness.

        Also recovers a snapshot file left behind by a previous process (service
        restarted mid-party): the file is the truth about the pre-party state even
        though this process never activated the blackout.
        """
        if self._snapshot is None and self._path.exists():
            self._snapshot = json.loads(self._path.read_text())["lights"]
            log.warning("restoring orphaned pre-party light snapshot from %s", self._path)
        if self._snapshot is None:
            return
        failures = 0
        for light_id, brightness in self._snapshot.items():
            try:
                await self._lights.set_state(
                    light_id, on=True, brightness=brightness, transition_time=ON_TRANSITION_MS
                )
            except Exception:
                failures += 1
                log.warning("could not restore light %s after the party", light_id, exc_info=True)
        log.info(
            "party blackout off: %d lights restored (%d failures)",
            len(self._snapshot),
            failures,
        )
        self._snapshot = None
        self._path.unlink(missing_ok=True)


async def all_lights_on(
    lights: LightsBackend, *, brightness: float, mirek: int, transition_ms: int = ON_TRANSITION_MS
) -> None:
    """Party's over: every bulb on in a uniform scene (cool white, bright)."""
    failures = 0
    total = 0
    for light in lights:
        total += 1
        try:
            await lights.set_state(
                light.id,
                on=True,
                brightness=brightness,
                color_temp=mirek,
                transition_time=transition_ms,
            )
        except Exception:
            failures += 1
            log.warning("could not apply party-over scene to light %s", light.id, exc_info=True)
    log.info("party-over scene applied to %d lights (%d failures)", total, failures)
