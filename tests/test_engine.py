import pytest
from conftest import CHANNELS, af

from hue_party.config import ShowConfig
from hue_party.engine import PANIC_COLOR, EffectEngine
from hue_party.models import ChannelColor
from hue_party.palettes import PALETTES


def make_engine() -> EffectEngine:
    return EffectEngine(CHANNELS, ShowConfig())


def test_renders_default_mode_for_all_channels() -> None:
    engine = make_engine()
    lf = engine.render(af(beat=True, low=1.0))
    assert set(lf.channels) == {0, 1, 2, 3}
    assert lf.channels[0] == PALETTES["fiesta"].color(1, 1.0)


def test_unknown_mode_and_palette_raise() -> None:
    engine = make_engine()
    with pytest.raises(ValueError):
        engine.set_mode("disco-nope")
    with pytest.raises(ValueError):
        engine.set_palette("nope")


def test_brightness_cap_scales_output() -> None:
    engine = make_engine()
    engine.brightness_cap = 0.5
    lf = engine.render(af(beat=True, low=1.0))
    full = PALETTES["fiesta"].color(1, 1.0)
    assert lf.channels[0].red == int(full.red * 0.5)


def test_panic_overrides_everything() -> None:
    engine = make_engine()
    engine.panic = True
    lf = engine.render(af(beat=True, low=1.0))
    assert all(c == PANIC_COLOR for c in lf.channels.values())
    assert lf.white is not None and lf.white.brightness == 100.0


def test_drop_strobes_for_its_duration_then_returns_to_mode() -> None:
    engine = make_engine()  # ShowConfig default drop_duration_s = 5.0
    engine.start_drop(now=0.0)
    strobe_on = engine.render(af(t=0.0))
    assert strobe_on.channels[0] == ChannelColor(65535, 65535, 65535)
    # half a strobe period later (8 Hz cap -> period 0.125s): lights off
    strobe_off = engine.render(af(t=0.125 / 2 + 0.001))
    assert strobe_off.channels[0] == ChannelColor(0, 0, 0)
    still = engine.render(af(t=4.9))
    assert still.channels[0] in (ChannelColor(65535, 65535, 65535), ChannelColor(0, 0, 0))
    after = engine.render(af(t=5.1, beat=True, low=1.0))
    assert after.channels[0] != ChannelColor(0, 0, 0)  # normal mode resumed


def test_drop_state_reports_remaining_time() -> None:
    engine = make_engine()
    assert engine.drop_state(t=0.0) == {"active": False, "remaining_s": 0.0, "duration_s": 5.0}
    engine.start_drop(now=10.0)
    state = engine.drop_state(t=12.0)
    assert state["active"] is True
    assert state["remaining_s"] == pytest.approx(3.0)
    assert engine.drop_state(t=15.5)["active"] is False


def test_drop_restart_while_active_extends_from_now() -> None:
    engine = make_engine()
    engine.start_drop(now=0.0)
    engine.start_drop(now=4.0)  # re-tap: restart the window
    assert engine.drop_state(t=8.0)["active"] is True


def test_crowd_vote_tints_output() -> None:
    engine = make_engine()
    baseline = engine.render(af(beat=True, low=1.0)).channels[0]
    engine2 = make_engine()
    for _ in range(8):
        engine2.crowd.vote(1.0 / 3.0, now=0.0)  # everyone votes green
    tinted = engine2.render(af(beat=True, low=1.0)).channels[0]
    assert tinted.green >= baseline.green
    assert tinted != baseline


def test_white_cue_every_eighth_beat() -> None:
    engine = make_engine()
    cues = []
    for i in range(20):
        lf = engine.render(af(t=i * 0.5, beat=True, volume=0.5, low=1.0))
        cues.append(lf.white)
    assert sum(c is not None for c in cues) == 2  # beats 8 and 16
    cue = next(c for c in cues if c is not None)
    assert 1.0 <= cue.brightness <= 100.0
