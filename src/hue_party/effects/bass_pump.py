"""Near-dark floor between beats; a full slam exactly on the beat."""

import math

from hue_party.effects.base import Effect
from hue_party.models import AudioFrame, ChannelColor, ChannelInfo
from hue_party.palettes import Palette, hsv_to_rgb16

FLOOR = 0.06  # dim glow between beats: enough to not read as "off"
DECAY_PER_S = 9.0  # fast fall after the slam is what makes the thump


class BassPump(Effect):
    name = "bass_pump"

    def __init__(self, channels: list[ChannelInfo]) -> None:
        super().__init__(channels)
        self._level = 0.0
        self._index = 0
        self._last_t: float | None = None

    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        if frame.is_beat:
            self._level = 0.4 + 0.6 * frame.low  # slam strength scales with bass energy
            self._index += 1
        else:
            self._level *= math.exp(-DECAY_PER_S * dt)
        value = FLOOR + (1.0 - FLOOR) * self._level
        base = palette.color(self._index, value)
        colors = {ch.channel_id: base for ch in self.channels}
        sub = min(self.channels, key=lambda c: c.z)
        colors[sub.channel_id] = hsv_to_rgb16(0.0, 0.0, self._level)
        return colors
