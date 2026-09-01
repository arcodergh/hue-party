"""Ring buffer that releases light frames after a configurable delay.

This is what lines the lights up with what the Sonos actually plays: frames are
computed against near-zero-latency captured audio, then held for the speaker's
transport delay before being sent to the bridge.
"""

from collections import deque

from hue_party.models import LightFrame


class DelayBuffer:
    def __init__(self) -> None:
        self._frames: deque[LightFrame] = deque()

    def push(self, frame: LightFrame) -> None:
        self._frames.append(frame)

    def pop_due(self, now: float, offset_s: float) -> list[LightFrame]:
        """Return all frames whose release time has arrived, oldest first."""
        due: list[LightFrame] = []
        while self._frames and self._frames[0].timestamp + offset_s <= now:
            due.append(self._frames.popleft())
        return due

    def __len__(self) -> int:
        return len(self._frames)
