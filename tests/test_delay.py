from hue_party.delay import DelayBuffer
from hue_party.models import LightFrame


def test_frame_held_until_offset_elapses() -> None:
    b = DelayBuffer()
    b.push(LightFrame(timestamp=10.0))
    assert b.pop_due(now=10.5, offset_s=1.0) == []
    assert len(b) == 1
    due = b.pop_due(now=11.0, offset_s=1.0)
    assert [f.timestamp for f in due] == [10.0]
    assert len(b) == 0


def test_all_due_frames_released_in_order() -> None:
    b = DelayBuffer()
    for t in (1.0, 2.0, 3.0):
        b.push(LightFrame(timestamp=t))
    due = b.pop_due(now=10.0, offset_s=0.0)
    assert [f.timestamp for f in due] == [1.0, 2.0, 3.0]
    assert b.pop_due(now=10.0, offset_s=0.0) == []


def test_zero_offset_releases_immediately() -> None:
    b = DelayBuffer()
    b.push(LightFrame(timestamp=5.0))
    assert len(b.pop_due(now=5.0, offset_s=0.0)) == 1
