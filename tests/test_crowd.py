import pytest

from hue_party.crowd import CrowdColor


def test_no_votes_means_zero_strength() -> None:
    assert CrowdColor().current(now=0.0) == (0.0, 0.0)


def test_single_vote_sets_hue() -> None:
    c = CrowdColor(saturate_votes=4.0)
    c.vote(0.5, now=0.0)
    hue, strength = c.current(now=0.0)
    assert hue == pytest.approx(0.5, abs=1e-6)
    assert strength == pytest.approx(0.25)


def test_votes_accumulate_toward_full_strength() -> None:
    c = CrowdColor(saturate_votes=4.0)
    for _ in range(8):
        c.vote(0.5, now=0.0)
    assert c.current(now=0.0)[1] == 1.0


def test_influence_decays_with_half_life() -> None:
    c = CrowdColor(half_life_s=10.0, saturate_votes=4.0)
    c.vote(0.5, now=0.0)
    _, strength = c.current(now=10.0)
    assert strength == pytest.approx(0.125, abs=1e-6)


def test_opposite_hues_cancel() -> None:
    c = CrowdColor()
    c.vote(0.0, now=0.0)
    c.vote(0.5, now=0.0)  # opposite side of the hue circle
    assert c.current(now=0.0)[1] == pytest.approx(0.0, abs=1e-9)
