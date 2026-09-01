"""Core message types passed between modules."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AudioFrame:
    """One analysis tick (~60/sec) describing what the music is doing right now."""

    timestamp: float  # time.monotonic() at capture
    is_beat: bool
    is_onset: bool
    tempo_bpm: float
    volume: float  # 0..1
    low: float  # 0..1 normalized band energies
    mid: float
    high: float


@dataclass(frozen=True, slots=True)
class ChannelColor:
    """16-bit RGB as required by the Hue Entertainment wire format."""

    red: int  # 0..65535
    green: int
    blue: int


@dataclass(frozen=True, slots=True)
class ChannelInfo:
    """An entertainment-area channel and its position in the room (each axis -1..1)."""

    channel_id: int
    x: float
    y: float
    z: float


@dataclass(frozen=True, slots=True)
class WhiteCue:
    """Coarse command for non-entertainment white bulbs."""

    brightness: float  # percent, 1..100 (aiohue: cannot be 0)
    transition_ms: int


@dataclass(frozen=True, slots=True)
class LightFrame:
    """One rendered output tick: a color per entertainment channel, optional white cue."""

    timestamp: float
    channels: dict[int, ChannelColor] = field(default_factory=dict)
    white: WhiteCue | None = None
