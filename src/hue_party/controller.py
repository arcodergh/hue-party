"""Single control surface over the show. Web, and later Home Assistant, talk to this."""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Protocol

from hue_party.effects import EFFECTS
from hue_party.engine import EffectEngine
from hue_party.history import PlayHistory
from hue_party.music import MusicControl
from hue_party.palettes import PALETTES
from hue_party.player import PlayerError
from hue_party.prefs import Prefs
from hue_party.speakers import SpeakerControl
from hue_party.streamer import LightStreamer


class PlayerLike(Protocol):
    async def play_pause(self) -> None: ...
    async def next_track(self) -> None: ...
    async def previous_track(self) -> None: ...
    async def now_playing(self) -> str | None: ...
    async def art_url(self) -> str | None: ...
    async def stop(self) -> None: ...
    async def pause(self) -> None: ...
    async def play(self) -> None: ...


class WatchdogLike(Protocol):
    async def stop_party(self) -> None: ...
    async def poll_once(self) -> None: ...


class CalibratorLike(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


class AnalyzerLike(Protocol):
    @property
    def beat_engine(self) -> str: ...
    @property
    def beat_engines(self) -> list[str]: ...
    def set_beat_engine(self, name: str) -> None: ...


class ShowController:
    def __init__(
        self,
        engine: EffectEngine,
        streamer: LightStreamer | None = None,
        player: PlayerLike | None = None,
        speakers: SpeakerControl | None = None,
        music: MusicControl | None = None,
        analyzer: AnalyzerLike | None = None,
        watchdog: WatchdogLike | None = None,
        party_over: Callable[[], Awaitable[None]] | None = None,
        history: PlayHistory | None = None,
        calibrator: CalibratorLike | None = None,
        prefs: Prefs | None = None,
        status: dict[str, str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._engine = engine
        self._streamer = streamer
        self.player = player
        self.speakers = speakers
        self.music = music
        self.analyzer = analyzer
        self.watchdog = watchdog
        self._party_over = party_over
        self.history = history
        self.calibrator = calibrator
        self._prefs = prefs
        self._status = status if status is not None else {}
        self._clock = clock
        self._changed = asyncio.Event()
        self.track: str | None = None
        self._pre_calibration_mode = engine.mode

    def _touch(self) -> None:
        self._changed.set()

    def _remember(self, key: str, value: object) -> None:
        if self._prefs is not None:
            self._prefs.set(key, value)

    async def wait_change(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
        except TimeoutError:
            return
        self._changed.clear()

    def state(self) -> dict[str, object]:
        hue, strength = self._engine.crowd.current(self._clock())
        engine_state: dict[str, object] = {}
        if self.analyzer is not None:
            engine_state = {
                "beat_engine": self.analyzer.beat_engine,
                "beat_engines": self.analyzer.beat_engines,
            }
        return engine_state | {
            "mode": self._engine.mode,
            "modes": sorted(set(EFFECTS) - {"calibration"}),
            "calibration": self._engine.mode == "calibration",
            "palette": self._engine.palette_name,
            "palettes": sorted(PALETTES),
            "offset_ms": self._streamer.offset_ms if self._streamer else 0,
            "brightness_cap": self._engine.brightness_cap,
            "panic": self._engine.panic,
            "drop": self._engine.drop_state(self._clock()),
            "crowd": {"hue": hue, "strength": strength},
            "track": self.track,
            "status": dict(self._status),
        }

    def set_mode(self, name: str) -> None:
        self._engine.set_mode(name)
        if name != "calibration":  # calibration is transient, never a startup mode
            self._remember("mode", name)
        self._touch()

    async def stop_party(self) -> None:
        """Hard stop: silence the player, end the light show, bring the house lights up."""
        if self.player is not None:
            with contextlib.suppress(PlayerError):  # no player running is not an error
                await self.player.stop()
        if self.watchdog is not None:
            await self.watchdog.stop_party()
        if self._party_over is not None:
            await self._party_over()  # every bulb on: uniform bright cool-white scene
        self._touch()

    def set_beat_engine(self, name: str) -> None:
        if self.analyzer is None:
            raise RuntimeError("No analyzer attached; beat engine cannot be changed")
        self.analyzer.set_beat_engine(name)
        self._remember("beat_engine", name)
        self._touch()

    async def set_calibration(self, on: bool) -> None:
        """Enter/leave calibration mode, restoring whatever mode was active before.

        Calibration is a metronome, not music: playback pauses, the calibrator
        drives clicks and flashes, and everything resumes when the toggle clears.
        """
        if on and self._engine.mode != "calibration":
            self._pre_calibration_mode = self._engine.mode
            self._engine.set_mode("calibration")
            if self.player is not None:
                with contextlib.suppress(PlayerError):  # silence is fine for calibrating
                    await self.player.pause()
            if self.calibrator is not None:
                self.calibrator.start()
            if self.watchdog is not None:
                await self.watchdog.poll_once()  # bring the light stream up right now
        elif not on and self._engine.mode == "calibration":
            if self.calibrator is not None:
                self.calibrator.stop()
            self._engine.set_mode(self._pre_calibration_mode)
            if self.player is not None:
                with contextlib.suppress(PlayerError):
                    await self.player.play()
        self._touch()

    def set_palette(self, name: str) -> None:
        self._engine.set_palette(name)
        self._remember("palette", name)
        self._touch()

    def set_offset(self, ms: int) -> None:
        if self._streamer is not None:
            self._streamer.offset_ms = ms
        self._remember("offset_ms", ms)
        self._touch()

    def set_brightness(self, cap: float) -> None:
        self._engine.brightness_cap = cap
        self._remember("brightness_cap", cap)
        self._touch()

    def set_panic(self, on: bool) -> None:
        self._engine.panic = on
        self._touch()

    def drop_start(self) -> None:
        self._engine.start_drop(self._clock())
        self._touch()

    def vote(self, hue: float) -> None:
        self._engine.crowd.vote(hue, self._clock())
        self._touch()
