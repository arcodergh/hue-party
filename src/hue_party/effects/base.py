"""Effect contract: AudioFrame in, per-channel colors out, at ~60 calls/sec."""

from abc import ABC, abstractmethod
from typing import ClassVar

from hue_party.models import AudioFrame, ChannelColor, ChannelInfo
from hue_party.palettes import Palette


class Effect(ABC):
    name: ClassVar[str]

    def __init__(self, channels: list[ChannelInfo]) -> None:
        self.channels = channels

    @abstractmethod
    def render(self, frame: AudioFrame, palette: Palette, t: float) -> dict[int, ChannelColor]:
        """Return a color for every channel this effect drives."""
