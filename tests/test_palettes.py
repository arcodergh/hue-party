from hue_party.models import ChannelColor
from hue_party.palettes import PALETTES, blend, hsv_to_rgb16, scale


def test_hsv_primaries() -> None:
    assert hsv_to_rgb16(0.0, 1.0, 1.0) == ChannelColor(65535, 0, 0)
    assert hsv_to_rgb16(1.0 / 3.0, 1.0, 1.0) == ChannelColor(0, 65535, 0)


def test_value_scales_brightness() -> None:
    assert hsv_to_rgb16(0.0, 1.0, 0.5).red == 32767


def test_scale_clamps_to_valid_range() -> None:
    assert scale(ChannelColor(65535, 0, 100), 2.0) == ChannelColor(65535, 0, 200)
    assert scale(ChannelColor(65535, 65535, 65535), 0.5).red == 32767


def test_blend_endpoints() -> None:
    a, b = ChannelColor(65535, 0, 0), ChannelColor(0, 65535, 0)
    assert blend(a, b, 0.0) == a
    assert blend(a, b, 1.0) == b
    assert blend(a, b, 0.5).red == 32767


def test_palette_index_wraps() -> None:
    p = PALETTES["fiesta"]
    assert p.color(0, 1.0) == p.color(len(p.hues), 1.0)


def test_all_palettes_have_at_least_three_hues() -> None:
    assert set(PALETTES) >= {"fiesta", "neon", "sunset", "ice"}
    for p in PALETTES.values():
        assert len(p.hues) >= 3
