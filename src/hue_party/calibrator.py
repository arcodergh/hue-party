"""Deterministic light-delay calibration: a metronome, not a beat detector.

Live, a flash lands at ``T_beat + D_engine + offset`` while the ear hears the beat
at ``T_beat + L_sonos`` — the slider is really tuning ``L_sonos - D_engine``, which
depends on the active beat engine's detection latency. So calibration plays a click
into ``music_bus`` (the real speaker path) and *directly* schedules a flash at
``T_click + D_engine`` into the normal delay buffer — no detector in the loop.

``D_engine`` is measured on this machine at every calibration start (machines
differ, and the measurement costs about a second): synthetic kicks are pushed
through a fresh analyzer pipeline and detection timestamps are compared with the
true onset grid.
"""

import asyncio
import logging
import math
import statistics
import time
import wave
from collections.abc import Awaitable, Callable
from pathlib import Path

import numpy as np

from hue_party.config import AudioConfig

log = logging.getLogger(__name__)

DEFAULT_CLICK_PATH = Path("~/.config/hue-party/click.wav")
CLICK_SAMPLE_RATE = 44100
CLICK_S = 0.008
CLICK_HZ = 1500.0
TICK_INTERVAL_S = 1.0

MEASURE_BPM = 128.0
MEASURE_TOTAL_S = 16.0
MEASURE_SKIP_S = 6.0  # engines need a few seconds to lock before we trust timings


def generate_click(path: Path) -> None:
    """Write a short, sharp click WAV (stdlib only) for the calibration metronome."""
    n = int(CLICK_SAMPLE_RATE * CLICK_S)
    t = np.arange(n) / CLICK_SAMPLE_RATE
    burst = np.sin(2 * math.pi * CLICK_HZ * t) * np.exp(-t * 400.0)
    samples = (burst * 0.9 * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(CLICK_SAMPLE_RATE)
        w.writeframes(samples.tobytes())


def measure_beat_latency_ms(engine_name: str, cfg: AudioConfig) -> float:
    """Median detection latency of one beat engine on this machine, in ms.

    Feeds synthetic kicks through a fresh analyzer pipeline (never the live one —
    that would corrupt its runtime state) and compares each detection timestamp
    with the nearest true kick onset. Blocking CPU work: call via a thread.
    """
    from hue_party.analyzer import AudioAnalyzer  # runtime import: avoids a module cycle

    analyzer = AudioAnalyzer(cfg, lambda frame: None)
    analyzer.set_beat_engine(engine_name)
    hop = cfg.sample_rate // cfg.fps
    period_s = 60.0 / MEASURE_BPM
    latencies: list[float] = []
    for i in range(int(MEASURE_TOTAL_S * cfg.fps)):
        t = (np.arange(hop) + i * hop) / cfg.sample_rate
        envelope = ((t % period_s) < 0.05).astype(np.float32)
        chunk = (0.9 * envelope * np.sin(2 * math.pi * 60.0 * t)).astype(np.float32)
        frame = analyzer.process(chunk, now=(i + 1) * hop / cfg.sample_rate)
        if frame.is_beat and frame.timestamp >= MEASURE_SKIP_S:
            nearest = round(frame.timestamp / period_s) * period_s
            latencies.append((frame.timestamp - nearest) * 1000.0)
    if not latencies:
        log.warning("latency measurement found no beats for %s; assuming 0ms", engine_name)
        return 0.0
    return float(statistics.median(latencies))


class Calibrator:
    """Runs the metronome: measure the active engine, then click + flash every second."""

    def __init__(
        self,
        *,
        measure: Callable[[str], Awaitable[float]],
        active_engine: Callable[[], str],
        play_click: Callable[[], Awaitable[None]],
        submit_flash: Callable[[float], None],
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        interval_s: float = TICK_INTERVAL_S,
    ) -> None:
        self._measure = measure
        self._active_engine = active_engine
        self._play_click = play_click
        self._submit_flash = submit_flash
        self._clock = clock
        self._sleep = sleeper
        self._interval_s = interval_s
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        engine = self._active_engine()
        try:
            latency_ms = await self._measure(engine)  # fresh, on THIS machine
        except Exception:
            log.exception("beat latency measurement failed; calibrating without it")
            latency_ms = 0.0
        log.info("calibrating for engine %s (detection latency %.0fms)", engine, latency_ms)
        while True:
            now = self._clock()
            try:
                await self._play_click()
            except Exception:
                log.warning("calibration click failed", exc_info=True)
            self._submit_flash(now + latency_ms / 1000.0)
            await self._sleep(self._interval_s)
