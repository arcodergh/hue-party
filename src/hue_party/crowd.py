"""Decaying circular average of guest hue votes ("the crowd's color")."""

import math


class CrowdColor:
    def __init__(self, half_life_s: float = 10.0, saturate_votes: float = 4.0) -> None:
        self._half_life_s = half_life_s
        self._saturate = saturate_votes
        self._x = 0.0
        self._y = 0.0
        self._last_t = 0.0

    def _decay_to(self, now: float) -> None:
        dt = max(0.0, now - self._last_t)
        if dt:
            factor = 0.5 ** (dt / self._half_life_s)
            self._x *= factor
            self._y *= factor
        self._last_t = now

    def vote(self, hue: float, now: float) -> None:
        self._decay_to(now)
        self._x += math.cos(math.tau * hue)
        self._y += math.sin(math.tau * hue)

    def current(self, now: float) -> tuple[float, float]:
        self._decay_to(now)
        magnitude = math.hypot(self._x, self._y)
        if magnitude < 1e-6:
            return (0.0, 0.0)
        hue = (math.atan2(self._y, self._x) / math.tau) % 1.0
        return (hue, min(1.0, magnitude / self._saturate))
