"""Left and right halves of the room trade the beat back and forth."""

import math

from hue_party.effects.base import Effect
from hue_party.models import AudioFrame, ChannelColor, ChannelInfo
from hue_party.palettes import Palette

DECAY_PER_S = 5.0
FLOOR = 0.04  # the resting side stays just barely visible


class PingPong(Effect):
    name = "ping_pong"

    def __init__(self, channels: list[ChannelInfo]) -> None:
        super().__init__(channels)
        self._side = 0  # 0 = left (x < 0), 1 = right
        self._level = 0.0
        self._index = 0
        self._last_t: float | None = None

    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        if frame.is_beat:
            self._side = 1 - self._side
            self._level = 1.0
            self._index += 1
        else:
            self._level *= math.exp(-DECAY_PER_S * dt)
        value = self._level * (0.35 + 0.65 * frame.low)
        colors: dict[int, ChannelColor] = {}
        for ch in self.channels:
            active = (ch.x >= 0) == (self._side == 1)
            colors[ch.channel_id] = palette.color(self._index, value if active else FLOOR)
        return colors
