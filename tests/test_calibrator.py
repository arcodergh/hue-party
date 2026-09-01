import asyncio
import wave
from pathlib import Path

from hue_party.calibrator import Calibrator, generate_click, measure_beat_latency_ms
from hue_party.config import AudioConfig


def test_generate_click_writes_a_short_nonsilent_wav(tmp_path: Path) -> None:
    path = tmp_path / "click.wav"
    generate_click(path)
    with wave.open(str(path)) as w:
        assert w.getframerate() == 44100
        frames = w.readframes(w.getnframes())
        assert w.getnframes() < 44100 // 10  # well under 100ms
    assert any(b != 0 for b in frames)


def test_measure_beat_latency_returns_plausible_ms_for_classic() -> None:
    # Runs the real aubio pipeline on synthetic kicks; must be fast and sane.
    latency = measure_beat_latency_ms("classic", AudioConfig())
    assert -20.0 <= latency <= 100.0


class Harness:
    def __init__(self) -> None:
        self.now = 100.0
        self.measured: list[str] = []
        self.clicks = 0
        self.flashes: list[float] = []
        self.slept: list[float] = []
        self.engine = "classic"

        async def measure(name: str) -> float:
            self.measured.append(name)
            return 30.0

        async def play_click() -> None:
            self.clicks += 1

        def submit_flash(at: float) -> None:
            self.flashes.append(at)

        async def sleeper(s: float) -> None:
            self.slept.append(s)
            if len(self.slept) >= 3:  # let a few ticks run, then stop the loop
                raise asyncio.CancelledError

        self.calibrator = Calibrator(
            measure=measure,
            active_engine=lambda: self.engine,
            play_click=play_click,
            submit_flash=submit_flash,
            clock=lambda: self.now,
            sleeper=sleeper,
        )


async def test_calibrator_measures_then_ticks_with_latency_compensation() -> None:
    h = Harness()
    h.calibrator.start()
    while h.calibrator.running:
        await asyncio.sleep(0)
    assert h.measured == ["classic"]  # measured on this machine, this session
    assert h.clicks == 3
    # flash scheduled at click time + measured engine latency (30ms)
    assert h.flashes[0] == 100.0 + 0.030


async def test_calibrator_remeasures_on_every_start() -> None:
    h = Harness()
    h.calibrator.start()
    while h.calibrator.running:
        await asyncio.sleep(0)
    h.engine = "predictive"
    h.calibrator.start()
    while h.calibrator.running:
        await asyncio.sleep(0)
    assert h.measured == ["classic", "predictive"]


async def test_stop_cancels_the_tick_loop() -> None:
    h = Harness()

    async def endless_sleep(_s: float) -> None:
        await asyncio.sleep(0)

    h.calibrator._sleep = endless_sleep
    h.calibrator.start()
    for _ in range(20):
        await asyncio.sleep(0)
    assert h.calibrator.running
    h.calibrator.stop()
    for _ in range(5):
        await asyncio.sleep(0)
    assert not h.calibrator.running
