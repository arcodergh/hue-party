import numpy as np

from hue_party.analyzer import AudioAnalyzer
from hue_party.config import AudioConfig
from hue_party.models import AudioFrame


def test_process_produces_populated_frames_from_synthetic_bass_pulses() -> None:
    cfg = AudioConfig()
    frames: list[AudioFrame] = []
    analyzer = AudioAnalyzer(cfg, frames.append)
    hop = cfg.sample_rate // cfg.fps  # 735
    t = np.arange(hop) / cfg.sample_rate
    sine = (0.8 * np.sin(2 * np.pi * 65.0 * t)).astype(np.float32)  # loud 65 Hz bass
    silence = np.zeros(hop, dtype=np.float32)
    beats = 0
    for i in range(240):  # 4 seconds: bass burst every 30 hops (~0.5s)
        chunk = sine if (i % 30) < 6 else silence
        frame = analyzer.process(chunk, now=i / cfg.fps)
        beats += frame.is_beat
    burst_frames = [analyzer.process(sine, now=5.0)]
    assert beats >= 4  # pulses every 0.5s must register as beats
    assert burst_frames[0].volume > 0.1
    assert burst_frames[0].low > burst_frames[0].high  # bass-heavy signal


def test_analyzer_engine_selection_and_listing() -> None:
    analyzer = AudioAnalyzer(AudioConfig(), lambda f: None)
    assert analyzer.beat_engine == "classic"
    assert "predictive" in analyzer.beat_engines
    analyzer.set_beat_engine("predictive")
    assert analyzer.beat_engine == "predictive"


def test_analyzer_rejects_unknown_engine() -> None:
    analyzer = AudioAnalyzer(AudioConfig(), lambda f: None)
    try:
        analyzer.set_beat_engine("vibes")
    except ValueError as exc:
        assert "vibes" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_analyzer_starts_on_configured_engine() -> None:
    analyzer = AudioAnalyzer(AudioConfig(beat_engine="predictive"), lambda f: None)
    assert analyzer.beat_engine == "predictive"
