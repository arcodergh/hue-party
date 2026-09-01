"""Terminal light simulator: develop effects without flashing the house."""

import sys
from collections.abc import Sequence

from hue_party.models import ChannelColor, ChannelInfo, LightFrame

BLACK = ChannelColor(0, 0, 0)

SIM_CHANNELS = [
    ChannelInfo(0, -1.0, 0.6, 0.0),
    ChannelInfo(1, -0.33, 0.9, 0.5),
    ChannelInfo(2, 0.33, 0.9, 0.5),
    ChannelInfo(3, 1.0, 0.6, -0.5),
]


def frame_to_ansi(frame: LightFrame, order: Sequence[int]) -> str:
    parts = []
    for cid in order:
        c = frame.channels.get(cid, BLACK)
        parts.append(f"\x1b[48;2;{c.red >> 8};{c.green >> 8};{c.blue >> 8}m    \x1b[0m")
    return " ".join(parts)


class TerminalRenderer:
    """Duck-types LightStreamer.submit so it can stand in as the light sink."""

    def __init__(self, order: Sequence[int]) -> None:
        self._order = list(order)

    def submit(self, frame: LightFrame) -> None:
        sys.stdout.write("\r" + frame_to_ansi(frame, self._order))
        sys.stdout.flush()
