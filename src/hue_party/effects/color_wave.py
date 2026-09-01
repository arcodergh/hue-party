"""Palette colors hop one light over on every beat, gliding across the room."""

from hue_party.effects.base import Effect
from hue_party.models import AudioFrame, ChannelColor, ChannelInfo
from hue_party.palettes import Palette, blend

GLIDE_S = 0.15  # short slide into the new color so the hop reads as movement


class ColorWave(Effect):
    name = "color_wave"

    def __init__(self, channels: list[ChannelInfo]) -> None:
        super().__init__(channels)
        ordered = sorted(channels, key=lambda c: c.x)
        self._rank = {ch.channel_id: i for i, ch in enumerate(ordered)}
        self._step = 0
        self._step_t: float | None = None

    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        if frame.is_beat:
            self._step += 1
            self._step_t = t
        value = 0.35 + 0.65 * frame.volume
        glide = 1.0 if self._step_t is None else min(1.0, (t - self._step_t) / GLIDE_S)
        colors: dict[int, ChannelColor] = {}
        for ch in self.channels:
            rank = self._rank[ch.channel_id]
            target = palette.color(rank + self._step, value)
            if glide < 1.0:
                target = blend(palette.color(rank + self._step - 1, value), target, glide)
            colors[ch.channel_id] = target
        return colors
