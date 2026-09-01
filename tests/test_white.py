from hue_party.models import WhiteCue
from hue_party.white import WhiteLights


class FakeBackend:
    def __init__(self, fail_ids: set[str] | None = None) -> None:
        self.calls: list[tuple[str, float, int]] = []
        self.fail_ids = fail_ids or set()

    async def set_state(
        self,
        id: str,
        *,
        on: bool | None = None,
        brightness: float | None = None,
        transition_time: int | None = None,
    ) -> None:
        if id in self.fail_ids:
            raise ConnectionError("bulb offline")
        assert brightness is not None and transition_time is not None
        self.calls.append((id, brightness, transition_time))


async def test_applies_to_all_bulbs() -> None:
    backend = FakeBackend()
    clock = [0.0]
    whites = WhiteLights(backend, ["a", "b"], clock=lambda: clock[0])
    await whites.apply(WhiteCue(brightness=70.0, transition_ms=400))
    assert [c[0] for c in backend.calls] == ["a", "b"]


async def test_rate_limited() -> None:
    backend = FakeBackend()
    clock = [0.0]
    whites = WhiteLights(backend, ["a"], min_interval_s=0.5, clock=lambda: clock[0])
    await whites.apply(WhiteCue(50.0, 400))
    clock[0] = 0.2
    await whites.apply(WhiteCue(60.0, 400))  # too soon -> dropped
    clock[0] = 0.6
    await whites.apply(WhiteCue(70.0, 400))
    assert [c[1] for c in backend.calls] == [50.0, 70.0]


async def test_one_dead_bulb_does_not_block_the_rest() -> None:
    backend = FakeBackend(fail_ids={"a"})
    whites = WhiteLights(backend, ["a", "b"], clock=lambda: 0.0)
    await whites.apply(WhiteCue(50.0, 400))
    assert [c[0] for c in backend.calls] == ["b"]


async def test_brightness_clamped_to_aiohue_range() -> None:
    backend = FakeBackend()
    whites = WhiteLights(backend, ["a"], clock=lambda: 0.0)
    await whites.apply(WhiteCue(brightness=0.0, transition_ms=100))  # aiohue: cannot be 0
    assert backend.calls[0][1] == 1.0
