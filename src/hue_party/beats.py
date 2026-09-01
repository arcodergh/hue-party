"""Beat engines: strategies that turn per-hop audio evidence into beat decisions.

All engines share one signature so the analyzer can hot-swap them from the UI:

- ``classic`` fires when a beat is *detected* (aubio or bass jump) — purely reactive.
- ``predictive`` runs a phase-locked tempo grid: aubio supplies the BPM, detections
  only nudge the grid's phase, and beats fire on the *predicted* pulse. Detections
  wobble hop-to-hop; the grid does not — which is what makes lights feel locked.
- ``neural`` (madmom, optional) is added by :mod:`hue_party.neural` when importable.
"""

import math
from typing import Protocol

import numpy as np

from hue_party.features import VolumeBeat

BPM_MIN = 60.0
BPM_MAX = 200.0
PHASE_ALPHA = 0.25  # fraction of observed phase error corrected per detection
OBS_TIMEOUT_S = 2.0  # no detections this long -> stop predicting (silence/breakdown)
DEFAULT_PERIOD_S = 0.5  # 120 BPM, until aubio reports a usable tempo


class BeatEngine(Protocol):
    def update(
        self, samples: np.ndarray, *, aubio_beat: bool, bpm: float, low: float, now: float
    ) -> bool: ...


class ClassicEngine:
    """Today's behavior: a beat is whatever aubio or the bass-jump detector says."""

    def __init__(self) -> None:
        self._volume_beat = VolumeBeat()

    def update(
        self, samples: np.ndarray, *, aubio_beat: bool, bpm: float, low: float, now: float
    ) -> bool:
        bass_beat = self._volume_beat.update(low, now)
        return aubio_beat or bass_beat


class PredictiveEngine:
    """Phase-locked tempo grid: schedule beats at the BPM period, corrected by detections."""

    def __init__(self) -> None:
        self._volume_beat = VolumeBeat()
        self._period = DEFAULT_PERIOD_S
        self._next: float | None = None  # next predicted beat time; None = unlocked
        self._last_obs = -math.inf

    def update(
        self, samples: np.ndarray, *, aubio_beat: bool, bpm: float, low: float, now: float
    ) -> bool:
        if BPM_MIN <= bpm <= BPM_MAX:
            self._period = 60.0 / bpm
        observed = aubio_beat or self._volume_beat.update(low, now)
        fired = False
        if observed:
            self._last_obs = now
            if self._next is None:
                fired = True  # first evidence after silence: fire and lock the grid
                self._next = now + self._period
            else:
                # Nudge phase toward the detection, relative to the nearest grid point.
                err_prev = now - (self._next - self._period)
                err_next = now - self._next
                error = err_prev if abs(err_prev) <= abs(err_next) else err_next
                self._next += PHASE_ALPHA * error
        if self._next is not None:
            if now - self._last_obs > OBS_TIMEOUT_S:
                self._next = None  # music stopped; predicted flashes would look wrong
            elif now >= self._next:
                fired = True
                while self._next <= now:  # catch up if the loop stalled a tick
                    self._next += self._period
        return fired


def default_engines() -> dict[str, BeatEngine]:
    """The always-available engines; optional ones are appended by their own modules."""
    return {"classic": ClassicEngine(), "predictive": PredictiveEngine()}
