"""Relaxed but in the groove: colors crossfade a step every 2nd (or 4th) beat."""

from hue_party.effects.base import Effect
from hue_party.models import AudioFrame, ChannelColor, ChannelInfo
from hue_party.palettes import Palette, blend

STEP_BEATS_SLOW = 2  # half-time on typical tracks
STEP_BEATS_FAST = 4  # quarter-time above FAST_BPM so it stays relaxed
FAST_BPM = 120.0
CROSSFADE_S = 2.0
VOLUME_SMOOTHING = 0.02


class ChillDrift(Effect):
    name = "chill_drift"

    def __init__(self, channels: list[ChannelInfo]) -> None:
        super().__init__(channels)
        self._beats = 0
        self._step = 0
        self._step_t: float | None = None
        self._volume = 0.3

    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        if frame.is_beat:
            self._beats += 1
            per_step = STEP_BEATS_FAST if frame.tempo_bpm > FAST_BPM else STEP_BEATS_SLOW
            if self._beats >= per_step:
                self._beats = 0
                self._step += 1
                self._step_t = t
        self._volume += (frame.volume - self._volume) * VOLUME_SMOOTHING
        value = 0.2 + 0.5 * self._volume
        fade = 1.0 if self._step_t is None else min(1.0, (t - self._step_t) / CROSSFADE_S)
        colors: dict[int, ChannelColor] = {}
        for i, ch in enumerate(self.channels):
            target = palette.color(i + self._step, value)
            if fade < 1.0:
                target = blend(palette.color(i + self._step - 1, value), target, fade)
            colors[ch.channel_id] = target
        return colors
