"""A single bright pulse jumps to the next light on each beat, tail fading."""

import math

from hue_party.effects.base import Effect
from hue_party.models import AudioFrame, ChannelColor, ChannelInfo
from hue_party.palettes import Palette

TAIL_DECAY_PER_S = 6.0


class PulseRun(Effect):
    name = "pulse_run"

    def __init__(self, channels: list[ChannelInfo]) -> None:
        super().__init__(channels)
        self._order = sorted(channels, key=lambda c: c.x)
        self._pos = 0
        self._index = 0
        self._levels = {ch.channel_id: 0.0 for ch in channels}
        self._last_t: float | None = None

    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        decay = math.exp(-TAIL_DECAY_PER_S * dt)
        for channel_id in self._levels:
            self._levels[channel_id] *= decay
        if frame.is_beat:
            self._pos = (self._pos + 1) % len(self._order)
            self._index += 1
            self._levels[self._order[self._pos].channel_id] = 1.0
        scale = 0.5 + 0.5 * frame.volume
        return {
            channel_id: palette.color(self._index, level * scale)
            for channel_id, level in self._levels.items()
        }
