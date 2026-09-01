"""Optional neural beat engine backed by madmom; registered only when importable.

madmom is an optional extra (``uv sync --extra neural``) because it builds from
source and is heavier than the party server's core needs. When it is absent the
UI simply doesn't offer the engine.

madmom's online models are trained at 44100 Hz, 100 fps (441-sample hops, 2048-sample
frames), while the analyzer delivers 60 fps hops (735 samples). :class:`NeuralEngine`
re-frames the live stream onto madmom's grid and runs the RNN + online-DBN pipeline
once per madmom frame; the DBN returns beat timestamps, which we collapse to
"a beat happened during this hop". ``reset=False`` must be threaded through every
call or the recurrent network and HMM never accumulate state.
"""

import logging
from collections.abc import Callable

import numpy as np

from hue_party.beats import BeatEngine

log = logging.getLogger(__name__)

MADMOM_SAMPLE_RATE = 44100
MADMOM_FPS = 100
MADMOM_HOP = 441
FRAME_SIZE = 2048

# One 2048-sample frame in, the pipeline's newly detected beat times (seconds) out.
StepFn = Callable[[np.ndarray], list[float]]


class NeuralEngine:
    """Re-frames live hops onto madmom's 100 fps grid and fires on DBN beats."""

    def __init__(self, step: StepFn) -> None:
        self._step = step
        self._buffer = np.zeros(FRAME_SIZE, dtype=np.float32)  # zero-primed history
        self._pending = 0  # samples not yet consumed by a madmom frame

    def update(
        self, samples: np.ndarray, *, aubio_beat: bool, bpm: float, low: float, now: float
    ) -> bool:
        self._buffer = np.concatenate((self._buffer, samples.astype(np.float32, copy=False)))
        self._pending += len(samples)
        fired = False
        while self._pending >= MADMOM_HOP:
            self._pending -= MADMOM_HOP
            end = len(self._buffer) - self._pending
            if self._step(self._buffer[end - FRAME_SIZE : end]):
                fired = True
        self._buffer = self._buffer[-(FRAME_SIZE + self._pending) :]
        return fired


def _build_madmom_step(sample_rate: int) -> StepFn:
    from madmom.audio.signal import Signal
    from madmom.features.beats import DBNBeatTrackingProcessor, RNNBeatProcessor
    from madmom.models import BEATS_LSTM

    # A single network keeps CPU cost trivial; origin='stream' makes the framer use
    # the *last* frame_size samples instead of zero-padding around a centered origin.
    rnn = RNNBeatProcessor(
        online=True,
        nn_files=[BEATS_LSTM[0]],
        fps=MADMOM_FPS,
        origin="stream",
        num_frames=1,
        num_threads=1,
    )
    dbn = DBNBeatTrackingProcessor(online=True, fps=MADMOM_FPS)

    def step(frame: np.ndarray) -> list[float]:
        signal = Signal(frame, sample_rate=sample_rate, num_channels=1)
        # A single frame yields a 0-d activation; the online DBN needs a 1-d array.
        activation = np.atleast_1d(np.asarray(rnn(signal, reset=False), dtype=np.float32))
        return list(dbn(activation, reset=False))

    return step


def add_neural_engine(engines: dict[str, BeatEngine], sample_rate: int) -> None:
    """Register the madmom-backed engine as ``neural`` when the library is available."""
    if sample_rate != MADMOM_SAMPLE_RATE:
        log.info("neural beat engine needs %d Hz capture; disabled", MADMOM_SAMPLE_RATE)
        return
    try:
        step = _build_madmom_step(sample_rate)
    except ImportError:
        log.info("madmom not installed; neural beat engine unavailable")
        return
    except Exception:
        log.exception("madmom failed to initialize; neural beat engine unavailable")
        return
    engines["neural"] = NeuralEngine(step)
