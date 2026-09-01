"""The show brain: picks the active effect, applies drop/panic overrides,
crowd tint, and the global brightness cap."""

import logging

from hue_party.config import ShowConfig
from hue_party.crowd import CrowdColor
from hue_party.effects import EFFECTS, Effect
from hue_party.models import AudioFrame, ChannelColor, ChannelInfo, LightFrame, WhiteCue
from hue_party.palettes import PALETTES, blend, hsv_to_rgb16, scale

log = logging.getLogger(__name__)

PANIC_COLOR = ChannelColor(65535, 39000, 14000)  # warm white
WHITE = ChannelColor(65535, 65535, 65535)
BLACK = ChannelColor(0, 0, 0)
CROWD_MAX_TINT = 0.5


class EffectEngine:
    def __init__(self, channels: list[ChannelInfo], show: ShowConfig) -> None:
        self._channels = channels
        self._show = show
        self._effects: dict[str, Effect] = {name: cls(channels) for name, cls in EFFECTS.items()}
        self._mode = show.default_mode
        self._palette_name = show.default_palette
        self.brightness_cap = show.brightness_cap
        self.panic = False
        self.crowd = CrowdColor()
        self._drop_end: float | None = None
        self._beat_count = 0

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def palette_name(self) -> str:
        return self._palette_name

    def set_mode(self, name: str) -> None:
        if name not in self._effects:
            raise ValueError(f"Unknown mode '{name}'. Available: {sorted(self._effects)}")
        self._mode = name

    def set_palette(self, name: str) -> None:
        if name not in PALETTES:
            raise ValueError(f"Unknown palette '{name}'. Available: {sorted(PALETTES)}")
        self._palette_name = name

    def start_drop(self, now: float) -> None:
        """Run the strobe sequence for the configured duration (re-tap restarts it)."""
        self._drop_end = now + self._show.drop_duration_s

    def drop_state(self, t: float) -> dict[str, object]:
        remaining = 0.0 if self._drop_end is None else max(0.0, self._drop_end - t)
        return {
            "active": remaining > 0.0,
            "remaining_s": remaining,
            "duration_s": self._show.drop_duration_s,
        }

    def render(self, frame: AudioFrame) -> LightFrame:
        t = frame.timestamp
        if self.panic:
            return LightFrame(
                t,
                {c.channel_id: PANIC_COLOR for c in self._channels},
                white=WhiteCue(brightness=100.0, transition_ms=400),
            )
        colors = self._drop_colors(t)
        if colors is None:
            palette = PALETTES[self._palette_name]
            colors = self._effects[self._mode].render(frame, palette, t)
        colors = self._apply_crowd(colors, t)
        colors = {cid: scale(c, self.brightness_cap) for cid, c in colors.items()}
        return LightFrame(t, colors, white=self._white_cue(frame))

    def _white_cue(self, frame: AudioFrame) -> WhiteCue | None:
        if not frame.is_beat:
            return None
        self._beat_count += 1
        if self._beat_count % 8 != 0:
            return None
        return WhiteCue(brightness=30.0 + 60.0 * frame.volume, transition_ms=400)

    def _drop_colors(self, t: float) -> dict[int, ChannelColor] | None:
        if self._drop_end is None:
            return None
        if t >= self._drop_end:
            self._drop_end = None
            return None
        period = 1.0 / min(self._show.strobe_max_hz, 8.0)
        color = WHITE if (t % period) < period / 2 else BLACK
        return {c.channel_id: color for c in self._channels}

    def _apply_crowd(self, colors: dict[int, ChannelColor], t: float) -> dict[int, ChannelColor]:
        hue, strength = self.crowd.current(t)
        if strength == 0.0:
            return colors
        tint = hsv_to_rgb16(hue, 1.0, 1.0)
        weight = CROWD_MAX_TINT * strength
        return {cid: blend(c, tint, weight) for cid, c in colors.items()}
