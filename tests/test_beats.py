import numpy as np

from hue_party.beats import ClassicEngine, PredictiveEngine

HOP = np.zeros(735, dtype=np.float32)


def test_classic_fires_on_aubio_beat() -> None:
    engine = ClassicEngine()
    assert engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=0.0) is True
    assert engine.update(HOP, aubio_beat=False, bpm=120.0, low=0.0, now=0.1) is False


def test_classic_fires_on_bass_jump() -> None:
    engine = ClassicEngine()
    for i in range(12):
        engine.update(HOP, aubio_beat=False, bpm=120.0, low=0.1, now=i * 0.02)
    assert engine.update(HOP, aubio_beat=False, bpm=120.0, low=0.9, now=0.3) is True


def run_until(
    engine: PredictiveEngine, start: float, end: float, step: float = 0.01
) -> list[float]:
    """Advance the engine with no detections; return the times where it fired."""
    fired = []
    t = start
    while t < end:
        if engine.update(HOP, aubio_beat=False, bpm=120.0, low=0.0, now=t):
            fired.append(t)
        t += step
    return fired


def test_predictive_first_detection_fires_and_starts_grid() -> None:
    engine = PredictiveEngine()
    assert engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=0.0) is True


def test_predictive_fires_on_grid_without_detection() -> None:
    # At 120 BPM the grid period is 0.5s: after one real beat at t=0, the engine
    # must keep the pulse going on its own — that is the whole point.
    engine = PredictiveEngine()
    engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=0.0)
    fired = run_until(engine, 0.01, 1.24)
    assert len(fired) == 2
    assert abs(fired[0] - 0.5) < 0.03
    assert abs(fired[1] - 1.0) < 0.03


def test_predictive_nudges_phase_toward_late_detections() -> None:
    engine = PredictiveEngine()
    engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=0.0)
    run_until(engine, 0.01, 0.54)  # grid beat at ~0.5 has fired
    engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=0.55)  # detection is late
    fired = run_until(engine, 0.56, 1.2)
    assert len(fired) == 1
    assert fired[0] > 1.0  # grid shifted later, toward the observed phase


def test_predictive_goes_quiet_when_detections_stop() -> None:
    # Music stopped / breakdown: predicted flashes with no musical evidence look wrong.
    engine = PredictiveEngine()
    engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=0.0)
    fired = run_until(engine, 0.01, 4.0)
    assert not [t for t in fired if t > 2.5]


def test_predictive_relocks_after_silence() -> None:
    engine = PredictiveEngine()
    engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=0.0)
    run_until(engine, 0.01, 4.0)  # goes quiet
    assert engine.update(HOP, aubio_beat=True, bpm=120.0, low=0.0, now=5.0) is True
    fired = run_until(engine, 5.01, 5.6)
    assert len(fired) == 1 and abs(fired[0] - 5.5) < 0.03


def test_predictive_survives_invalid_bpm() -> None:
    engine = PredictiveEngine()
    assert engine.update(HOP, aubio_beat=True, bpm=0.0, low=0.0, now=0.0) is True
