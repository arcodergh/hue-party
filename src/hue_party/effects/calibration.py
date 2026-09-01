"""Latency calibration: hard white exactly on detected beats, black otherwise."""

from hue_party.effects.base import Effect
from hue_party.models import AudioFrame, ChannelColor
from hue_party.palettes import Palette

WHITE = ChannelColor(65535, 65535, 65535)
BLACK = ChannelColor(0, 0, 0)


class Calibration(Effect):
    name = "calibration"

    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        color = WHITE if frame.is_beat else BLACK
        return {ch.channel_id: color for ch in self.channels}
