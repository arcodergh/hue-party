import numpy as np

from hue_party.features import BandExtractor, VolumeBeat


def spectrum(fft_size: int, hot: slice) -> np.ndarray:
    mags = np.zeros(fft_size // 2 + 1, dtype=np.float32)
    mags[hot] = 10.0
    return mags


def test_low_band_energy_lands_in_low() -> None:
    ex = BandExtractor(sample_rate=44100, fft_size=4096)
    # bin freq = i * 44100 / 4096 ≈ 10.77 Hz; bins 4..20 ≈ 43..215 Hz -> low band (20-250 Hz)
    low, mid, high = ex.extract(spectrum(4096, slice(4, 20)))
    assert low == 1.0  # first sight of energy defines the peak
    assert mid == 0.0 and high == 0.0


def test_high_band_energy_lands_in_high() -> None:
    ex = BandExtractor(sample_rate=44100, fft_size=4096)
    # bins 600..900 ≈ 6.4-9.7 kHz -> high band (4-16 kHz)
    low, mid, high = ex.extract(spectrum(4096, slice(600, 900)))
    assert high == 1.0 and low == 0.0 and mid == 0.0


def test_auto_gain_quiet_after_loud_reads_low() -> None:
    ex = BandExtractor(sample_rate=44100, fft_size=4096)
    ex.extract(spectrum(4096, slice(4, 20)))  # loud sets the peak
    quiet = spectrum(4096, slice(4, 20)) * 0.1
    low, _, _ = ex.extract(quiet)
    assert low < 0.2


def test_volume_beat_fires_on_bass_jump_then_respects_interval() -> None:
    vb = VolumeBeat(min_interval_s=0.1)
    for i in range(12):
        assert vb.update(0.1, now=i * 0.016) is False  # quiet, below min_level
    assert vb.update(0.9, now=0.5) is True  # jump over rolling average
    assert vb.update(0.9, now=0.55) is False  # too soon after last beat


def test_volume_beat_ignores_sustained_loudness_once_average_catches_up() -> None:
    vb = VolumeBeat(history_len=4, min_interval_s=0.0)
    for i in range(10):
        vb.update(0.9, now=i * 0.1)
    assert vb.update(0.9, now=2.0) is False  # 0.9 / avg(0.9) < min_ratio
