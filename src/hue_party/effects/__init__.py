"""Registry of available effect modes."""

from hue_party.effects.base import Effect
from hue_party.effects.bass_pump import BassPump
from hue_party.effects.beat_flash import BeatFlash
from hue_party.effects.calibration import Calibration
from hue_party.effects.chill_drift import ChillDrift
from hue_party.effects.color_wave import ColorWave
from hue_party.effects.ping_pong import PingPong
from hue_party.effects.pulse_run import PulseRun

EFFECTS: dict[str, type[Effect]] = {
    BeatFlash.name: BeatFlash,
    Calibration.name: Calibration,
    ColorWave.name: ColorWave,
    BassPump.name: BassPump,
    ChillDrift.name: ChillDrift,
    PulseRun.name: PulseRun,
    PingPong.name: PingPong,
}

__all__ = ["EFFECTS", "Effect"]
