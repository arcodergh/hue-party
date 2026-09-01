from hue_party.models import ChannelColor, LightFrame
from hue_party.simulator import frame_to_ansi


def test_frame_renders_truecolor_blocks_in_order() -> None:
    frame = LightFrame(
        timestamp=0.0,
        channels={0: ChannelColor(65535, 0, 0), 1: ChannelColor(0, 65535, 0)},
    )
    out = frame_to_ansi(frame, order=[0, 1])
    assert "\x1b[48;2;255;0;0m" in out
    assert "\x1b[48;2;0;255;0m" in out
    assert out.index("255;0;0") < out.index("0;255;0")


def test_missing_channel_renders_black() -> None:
    out = frame_to_ansi(LightFrame(timestamp=0.0), order=[7])
    assert "\x1b[48;2;0;0;0m" in out
