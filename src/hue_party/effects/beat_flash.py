"""All lights pulse on the beat; brightness rides the bass between beats."""

import math

from hue_party.effects.base import Effect
from hue_party.models import AudioFrame, ChannelColor, ChannelInfo
from hue_party.palettes import Palette

DECAY_PER_S = 4.0


class BeatFlash(Effect):
    name = "beat_flash"

    def __init__(self, channels: list[ChannelInfo]) -> None:
        super().__init__(channels)
        self._level = 0.0
        self._index = 0
        self._last_t: float | None = None

    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        if frame.is_beat:
            self._level = 1.0
            self._index += 1
        else:
            self._level *= math.exp(-DECAY_PER_S * dt)
        value = self._level * (0.35 + 0.65 * frame.low)
        color = palette.color(self._index, value)
        return {ch.channel_id: color for ch in self.channels}
