"""Pure audio feature extraction: band energies with auto-gain, bass-jump beat.

The VolumeBeat logic mirrors LedFx's volume_beat_now(): a beat fires when bass
power jumps well above its own rolling average, with a refractory interval.
"""

import math
from collections import deque
from typing import Final

import numpy as np

BAND_EDGES_HZ: Final = (20.0, 250.0, 4000.0, 16000.0)  # low | mid | high boundaries


class BandExtractor:
    def __init__(self, sample_rate: int, fft_size: int, decay: float = 0.999) -> None:
        hz_per_bin = sample_rate / fft_size
        n_bins = fft_size // 2 + 1
        edges = [min(int(hz / hz_per_bin), n_bins - 1) for hz in BAND_EDGES_HZ]
        self._slices = [slice(edges[i], max(edges[i + 1], edges[i] + 1)) for i in range(3)]
        self._peaks = [1e-6] * 3
        self._decay = decay

    def extract(self, magnitudes: np.ndarray) -> tuple[float, float, float]:
        out: list[float] = []
        for i, sl in enumerate(self._slices):
            energy = float(np.mean(magnitudes[sl]))
            self._peaks[i] = max(energy, self._peaks[i] * self._decay, 1e-6)
            out.append(min(1.0, energy / self._peaks[i]))
        return (out[0], out[1], out[2])


class VolumeBeat:
    def __init__(
        self,
        history_len: int = 12,
        min_ratio: float = 1.5,
        min_level: float = 0.2,
        min_interval_s: float = 0.1,
    ) -> None:
        self._history: deque[float] = deque(maxlen=history_len)
        self._min_ratio = min_ratio
        self._min_level = min_level
        self._min_interval_s = min_interval_s
        self._prev_beat_t = -math.inf

    def update(self, low: float, now: float) -> bool:
        avg = sum(self._history) / len(self._history) if self._history else 0.0
        fired = (
            low >= self._min_level
            and (avg == 0.0 or low / avg >= self._min_ratio)
            and now - self._prev_beat_t >= self._min_interval_s
        )
        self._history.append(low)
        if fired:
            self._prev_beat_t = now
        return fired
