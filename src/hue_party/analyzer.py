"""Audio capture (PipeWire monitor via sounddevice) and per-hop analysis (aubio)."""

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable

import aubio
import numpy as np
import sounddevice as sd

from hue_party.beats import BeatEngine, default_engines
from hue_party.config import AudioConfig
from hue_party.features import BandExtractor
from hue_party.models import AudioFrame
from hue_party.neural import add_neural_engine

log = logging.getLogger(__name__)


class AudioAnalyzer:
    def __init__(self, cfg: AudioConfig, on_frame: Callable[[AudioFrame], None]) -> None:
        self._cfg = cfg
        self._on_frame = on_frame
        hop = cfg.sample_rate // cfg.fps
        self._hop = hop
        self._tempo = aubio.tempo("default", cfg.fft_size, hop, cfg.sample_rate)
        self._onset = aubio.onset("hfc", cfg.fft_size, hop, cfg.sample_rate)
        self._pvoc = aubio.pvoc(cfg.fft_size, hop)
        self._bands = BandExtractor(cfg.sample_rate, cfg.fft_size)
        self._engines: dict[str, BeatEngine] = default_engines()
        add_neural_engine(self._engines, cfg.sample_rate)
        self._engine_name = cfg.beat_engine
        if self._engine_name not in self._engines:
            log.warning("configured beat engine %r unavailable; using classic", cfg.beat_engine)
            self._engine_name = "classic"
        self._dropped_frame_count = 0
        self._last_dropped_warning_time = 0.0

    @property
    def beat_engine(self) -> str:
        return self._engine_name

    @property
    def beat_engines(self) -> list[str]:
        return sorted(self._engines)

    def set_beat_engine(self, name: str) -> None:
        if name not in self._engines:
            raise ValueError(f"Unknown beat engine '{name}'. Available: {sorted(self._engines)}")
        self._engine_name = name

    def process(self, mono: np.ndarray, now: float) -> AudioFrame:
        """Analyze one hop of mono float32 samples into an AudioFrame."""
        samples = np.ascontiguousarray(mono, dtype=np.float32)
        aubio_beat = bool(self._tempo(samples)[0])
        is_onset = bool(self._onset(samples)[0])
        magnitudes = self._pvoc(samples).norm
        low, mid, high = self._bands.extract(magnitudes)
        volume = min(1.0, float(np.sqrt(np.mean(samples**2))) * 4.0)
        bpm = float(self._tempo.get_bpm())
        is_beat = self._engines[self._engine_name].update(
            samples, aubio_beat=aubio_beat, bpm=bpm, low=low, now=now
        )
        return AudioFrame(
            timestamp=now,
            is_beat=is_beat,
            is_onset=is_onset,
            tempo_bpm=bpm,
            volume=volume,
            low=low,
            mid=mid,
            high=high,
        )

    async def run(self) -> None:
        """Capture from the configured device and emit AudioFrames on the event loop."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[tuple[np.ndarray, float]] = asyncio.Queue(maxsize=8)

        def _enqueue(item: tuple[np.ndarray, float]) -> None:
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                # drop the frame; analysis is behind and stale audio is useless
                self._dropped_frame_count += 1
                now = time.monotonic()
                if now - self._last_dropped_warning_time >= 5.0:
                    log.warning(
                        "dropped %d audio frames due to analysis lag",
                        self._dropped_frame_count,
                    )
                    self._dropped_frame_count = 0
                    self._last_dropped_warning_time = now

        def callback(
            indata: np.ndarray, frames: int, time_info: object, status: sd.CallbackFlags
        ) -> None:
            if status:
                log.warning("audio capture status: %s", status)
            mono = indata.mean(axis=1).astype(np.float32)
            with contextlib.suppress(RuntimeError):  # loop shutting down
                loop.call_soon_threadsafe(_enqueue, (mono, loop.time()))

        with sd.InputStream(
            device=self._cfg.device,
            channels=2,
            samplerate=self._cfg.sample_rate,
            blocksize=self._hop,
            dtype="float32",
            callback=callback,
        ):
            log.info("capturing from %s at %d Hz", self._cfg.device, self._cfg.sample_rate)
            while True:
                try:
                    mono, captured_at = await queue.get()
                except asyncio.CancelledError:
                    raise
                self._on_frame(self.process(mono, captured_at))
