import numpy as np

from hue_party.neural import FRAME_SIZE, MADMOM_HOP, NeuralEngine


class FakeStep:
    """Stands in for the madmom RNN+DBN pipeline: one 2048-sample frame -> beat times."""

    def __init__(self) -> None:
        self.frames: list[np.ndarray] = []
        self.beats_to_report: list[float] = []

    def __call__(self, frame: np.ndarray) -> list[float]:
        self.frames.append(frame.copy())
        beats, self.beats_to_report = self.beats_to_report, []
        return beats


def hop(fill: float = 0.0, n: int = 735) -> np.ndarray:
    return np.full(n, fill, dtype=np.float32)


def test_reframes_60fps_hops_onto_madmom_100fps_grid() -> None:
    # 735 samples in -> one 441-hop frame (294 pending); next 735 -> two more.
    step = FakeStep()
    engine = NeuralEngine(step)
    engine.update(hop(), aubio_beat=False, bpm=120.0, low=0.0, now=0.0)
    assert len(step.frames) == 1
    engine.update(hop(), aubio_beat=False, bpm=120.0, low=0.0, now=0.02)
    assert len(step.frames) == 3
    assert all(len(f) == FRAME_SIZE for f in step.frames)


def test_frames_end_at_the_newest_consumed_sample() -> None:
    step = FakeStep()
    engine = NeuralEngine(step)
    samples = np.arange(735, dtype=np.float32)
    engine.update(samples, aubio_beat=False, bpm=120.0, low=0.0, now=0.0)
    # First madmom frame covers everything up to sample index MADMOM_HOP-1.
    assert step.frames[0][-1] == MADMOM_HOP - 1
    assert step.frames[0][0] == 0.0  # zero-primed history before the stream began


def test_fires_only_when_pipeline_reports_a_beat() -> None:
    step = FakeStep()
    engine = NeuralEngine(step)
    assert engine.update(hop(), aubio_beat=False, bpm=120.0, low=0.0, now=0.0) is False
    step.beats_to_report = [0.42]
    assert engine.update(hop(), aubio_beat=False, bpm=120.0, low=0.0, now=0.02) is True
