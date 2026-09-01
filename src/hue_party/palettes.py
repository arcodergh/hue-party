"""Color math and named palettes. Hues/saturations are 0..1 floats."""

import colorsys
from dataclasses import dataclass

from hue_party.models import ChannelColor

MAX = 65535


def hsv_to_rgb16(h: float, s: float, v: float) -> ChannelColor:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, min(1.0, max(0.0, s)), min(1.0, max(0.0, v)))
    return ChannelColor(int(r * MAX), int(g * MAX), int(b * MAX))


def scale(c: ChannelColor, factor: float) -> ChannelColor:
    def _s(x: int) -> int:
        return min(MAX, max(0, int(x * factor)))

    return ChannelColor(_s(c.red), _s(c.green), _s(c.blue))


def blend(a: ChannelColor, b: ChannelColor, w: float) -> ChannelColor:
    w = min(1.0, max(0.0, w))

    def _b(x: int, y: int) -> int:
        return int(x * (1 - w) + y * w)

    return ChannelColor(_b(a.red, b.red), _b(a.green, b.green), _b(a.blue, b.blue))


@dataclass(frozen=True)
class Palette:
    name: str
    hues: tuple[tuple[float, float], ...]  # (hue, saturation) pairs

    def color(self, index: int, value: float) -> ChannelColor:
        h, s = self.hues[index % len(self.hues)]
        return hsv_to_rgb16(h, s, value)


PALETTES: dict[str, Palette] = {
    "fiesta": Palette("fiesta", ((0.0, 1.0), (0.08, 1.0), (0.16, 1.0), (0.55, 1.0), (0.83, 1.0))),
    "neon": Palette("neon", ((0.85, 1.0), (0.5, 1.0), (0.33, 1.0), (0.75, 1.0))),
    "sunset": Palette("sunset", ((0.02, 1.0), (0.06, 0.9), (0.1, 0.8), (0.93, 0.7))),
    "ice": Palette("ice", ((0.55, 0.9), (0.6, 0.6), (0.66, 0.8), (0.5, 0.3))),
}
