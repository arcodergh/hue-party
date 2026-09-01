from conftest import CHANNELS, af

from hue_party.effects import EFFECTS
from hue_party.effects.bass_pump import BassPump
from hue_party.effects.beat_flash import BeatFlash
from hue_party.effects.calibration import Calibration
from hue_party.effects.chill_drift import ChillDrift
from hue_party.effects.color_wave import ColorWave
from hue_party.effects.pulse_run import PulseRun
from hue_party.models import ChannelColor
from hue_party.palettes import PALETTES

FIESTA = PALETTES["fiesta"]


def brightness(c: ChannelColor) -> int:
    return c.red + c.green + c.blue


def test_registry_contains_all_modes() -> None:
    expected = {"beat_flash", "calibration", "color_wave", "bass_pump", "chill_drift", "pulse_run"}
    assert expected <= set(EFFECTS)


def test_beat_flash_full_brightness_on_beat() -> None:
    fx = BeatFlash(CHANNELS)
    colors = fx.render(af(t=0.0, beat=True, low=1.0), FIESTA, t=0.0)
    assert set(colors) == {0, 1, 2, 3}
    assert colors[0] == FIESTA.color(1, 1.0)  # beat advanced palette index to 1


def test_beat_flash_decays_between_beats() -> None:
    fx = BeatFlash(CHANNELS)
    on_beat = fx.render(af(t=0.0, beat=True, low=1.0), FIESTA, t=0.0)
    later = fx.render(af(t=0.5, beat=False, low=1.0), FIESTA, t=0.5)
    assert later[0].red < on_beat[0].red


def test_beat_flash_cycles_palette_colors() -> None:
    fx = BeatFlash(CHANNELS)
    first = fx.render(af(beat=True, low=1.0), FIESTA, t=0.0)
    second = fx.render(af(t=1.0, beat=True, low=1.0), FIESTA, t=1.0)
    assert first[0] != second[0]


def test_calibration_white_on_beat_black_otherwise() -> None:
    fx = Calibration(CHANNELS)
    assert fx.render(af(beat=True), FIESTA, t=0.0)[0] == ChannelColor(65535, 65535, 65535)
    assert fx.render(af(beat=False), FIESTA, t=0.1)[0] == ChannelColor(0, 0, 0)


# --- color_wave: colors hop one light over on every beat -----------------------


def test_color_wave_neighbours_differ_and_chase_on_beat() -> None:
    fx = ColorWave(CHANNELS)
    before = fx.render(af(t=0.0, volume=1.0), FIESTA, t=0.0)
    assert before[0] != before[1]
    fx.render(af(t=1.0, beat=True, volume=1.0), FIESTA, t=1.0)
    after = fx.render(af(t=1.5, volume=1.0), FIESTA, t=1.5)  # glide finished
    # CHANNELS are already in x order: each light takes its right neighbour's color.
    assert after[0] == before[1]
    assert after[1] == before[2]


def test_color_wave_holds_still_without_beats() -> None:
    fx = ColorWave(CHANNELS)
    a = fx.render(af(t=0.0, volume=1.0), FIESTA, t=0.0)
    b = fx.render(af(t=2.0, volume=1.0), FIESTA, t=2.0)
    assert a == b


def test_color_wave_brightness_rides_volume() -> None:
    quiet = ColorWave(CHANNELS).render(af(volume=0.1), FIESTA, t=0.0)
    loud = ColorWave(CHANNELS).render(af(volume=1.0), FIESTA, t=0.0)
    assert brightness(loud[0]) > brightness(quiet[0])


# --- bass_pump: near-dark floor, full slam exactly on the beat -----------------


def test_bass_pump_slams_on_beat_and_falls_to_dark_floor() -> None:
    fx = BassPump(CHANNELS)
    slam = fx.render(af(t=0.0, beat=True, low=1.0), FIESTA, t=0.0)
    floor = fx.render(af(t=0.5, beat=False, low=1.0), FIESTA, t=0.5)
    assert brightness(floor[1]) < brightness(slam[1]) * 0.25  # thump contrast


def test_bass_pump_slam_strength_follows_bass() -> None:
    weak = BassPump(CHANNELS).render(af(beat=True, low=0.2), FIESTA, t=0.0)
    strong = BassPump(CHANNELS).render(af(beat=True, low=1.0), FIESTA, t=0.0)
    assert brightness(strong[1]) > brightness(weak[1])


def test_bass_pump_lowest_light_is_the_subwoofer() -> None:
    fx = BassPump(CHANNELS)
    colors = fx.render(af(beat=True, low=1.0, mid=1.0), FIESTA, t=0.0)
    sub = colors[3]  # channel 3 has the lowest z in CHANNELS
    assert sub.red == sub.green == sub.blue  # white-hot pulse, not palette color


# --- chill_drift: half-time steps, slow crossfades -----------------------------


def test_chill_drift_is_gentle() -> None:
    fx = ChillDrift(CHANNELS)
    a = fx.render(af(t=0.0, volume=0.5), FIESTA, t=0.0)
    b = fx.render(af(t=1 / 60, volume=0.5), FIESTA, t=1 / 60)
    diff = abs(a[0].red - b[0].red) + abs(a[0].green - b[0].green) + abs(a[0].blue - b[0].blue)
    assert diff < 2000  # no sudden jumps frame-to-frame


def test_chill_drift_steps_every_second_beat() -> None:
    fx = ChillDrift(CHANNELS)
    baseline = fx.render(af(t=0.0, volume=0.3, bpm=100.0), FIESTA, t=0.0)
    fx.render(af(t=0.6, beat=True, volume=0.3, bpm=100.0), FIESTA, t=0.6)
    unchanged = fx.render(af(t=3.0, volume=0.3, bpm=100.0), FIESTA, t=3.0)
    assert unchanged == baseline  # one beat is not enough at half-time
    fx.render(af(t=3.6, beat=True, volume=0.3, bpm=100.0), FIESTA, t=3.6)
    moved = fx.render(af(t=7.0, volume=0.3, bpm=100.0), FIESTA, t=7.0)  # crossfade done
    assert moved != baseline


def test_chill_drift_steps_every_fourth_beat_on_fast_tracks() -> None:
    fx = ChillDrift(CHANNELS)
    baseline = fx.render(af(t=0.0, volume=0.3, bpm=140.0), FIESTA, t=0.0)
    for i in (1, 2, 3):
        fx.render(af(t=float(i), beat=True, volume=0.3, bpm=140.0), FIESTA, t=float(i))
    assert fx.render(af(t=6.0, volume=0.3, bpm=140.0), FIESTA, t=6.0) == baseline
    fx.render(af(t=7.0, beat=True, volume=0.3, bpm=140.0), FIESTA, t=7.0)
    assert fx.render(af(t=10.0, volume=0.3, bpm=140.0), FIESTA, t=10.0) != baseline


# --- pulse_run: one pulse jumps light-to-light on each beat --------------------


def test_pulse_run_lights_exactly_one_light_per_beat() -> None:
    fx = PulseRun(CHANNELS)
    colors = fx.render(af(t=0.0, beat=True, volume=1.0), FIESTA, t=0.0)
    lit = [cid for cid, c in colors.items() if brightness(c) > 30000]
    dark = [cid for cid, c in colors.items() if brightness(c) < 5000]
    assert len(lit) == 1
    assert len(dark) == 3


def test_pulse_run_moves_to_the_next_light_on_the_next_beat() -> None:
    fx = PulseRun(CHANNELS)
    first = fx.render(af(t=0.0, beat=True, volume=1.0), FIESTA, t=0.0)
    second = fx.render(af(t=0.5, beat=True, volume=1.0), FIESTA, t=0.5)
    brightest = lambda cs: max(cs, key=lambda cid: brightness(cs[cid]))  # noqa: E731
    assert brightest(first) != brightest(second)


# --- ping_pong: room halves trade the beat -------------------------------------


def test_ping_pong_lights_one_half_and_swaps_on_next_beat() -> None:
    from hue_party.effects.ping_pong import PingPong

    fx = PingPong(CHANNELS)
    first = fx.render(af(t=0.0, beat=True, low=1.0), FIESTA, t=0.0)
    # CHANNELS: 0,1 are left (x<0) and 2,3 are right (x>=0)
    left = brightness(first[0]) + brightness(first[1])
    right = brightness(first[2]) + brightness(first[3])
    assert (left > right * 3) or (right > left * 3)  # one clear side
    second = fx.render(af(t=0.5, beat=True, low=1.0), FIESTA, t=0.5)
    swapped_left = brightness(second[0]) + brightness(second[1])
    assert (left > right) != (swapped_left > brightness(second[2]) + brightness(second[3]))


def test_ping_pong_registered() -> None:
    assert "ping_pong" in EFFECTS
