import json
from pathlib import Path

from hue_party.blackout import Blackout


class FakeLight:
    def __init__(self, id: str, on: bool, brightness: float | None) -> None:
        self.id = id
        self.on = type("On", (), {"on": on})()
        self.dimming = None if brightness is None else type("Dim", (), {"brightness": brightness})()


class FakeLights:
    """Mimics aiohue's LightsController: iterable, with set_state."""

    def __init__(self, lights: list[FakeLight]) -> None:
        self._lights = lights
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.fail_ids: set[str] = set()

    def __iter__(self):
        return iter(self._lights)

    async def set_state(
        self,
        id: str,
        *,
        on: bool | None = None,
        brightness: float | None = None,
        color_temp: int | None = None,
        transition_time: int | None = None,
    ) -> None:
        if id in self.fail_ids:
            raise ConnectionError("light unreachable")
        call: dict[str, object] = {"on": on, "brightness": brightness}
        if color_temp is not None:
            call["color_temp"] = color_temp
        self.calls.append((id, call))


def make(
    tmp_path: Path, lights: list[FakeLight], exclude: set[str] | None = None
) -> tuple[Blackout, FakeLights]:
    backend = FakeLights(lights)
    blackout = Blackout(backend, exclude_ids=exclude or set(), snapshot_path=tmp_path / "snap.json")
    return blackout, backend


async def test_activate_snapshots_and_turns_off_only_other_on_lights(tmp_path: Path) -> None:
    blackout, backend = make(
        tmp_path,
        [
            FakeLight("party", on=True, brightness=80.0),
            FakeLight("kitchen", on=True, brightness=60.0),
            FakeLight("hall", on=False, brightness=20.0),
        ],
        exclude={"party"},
    )
    await blackout.activate()
    assert backend.calls == [("kitchen", {"on": False, "brightness": None})]
    saved = json.loads((tmp_path / "snap.json").read_text())
    assert saved["lights"] == {"kitchen": 60.0}


async def test_restore_brings_lights_back_and_clears_snapshot(tmp_path: Path) -> None:
    blackout, backend = make(tmp_path, [FakeLight("kitchen", on=True, brightness=60.0)])
    await blackout.activate()
    backend.calls.clear()
    await blackout.restore()
    assert backend.calls == [("kitchen", {"on": True, "brightness": 60.0})]
    assert not (tmp_path / "snap.json").exists()


async def test_restore_handles_light_without_dimming(tmp_path: Path) -> None:
    blackout, backend = make(tmp_path, [FakeLight("plug", on=True, brightness=None)])
    await blackout.activate()
    backend.calls.clear()
    await blackout.restore()
    assert backend.calls == [("plug", {"on": True, "brightness": None})]


async def test_stale_snapshot_from_crash_wins_over_current_state(tmp_path: Path) -> None:
    # Crash mid-party: lights are still off, but the pre-party truth is in the file.
    (tmp_path / "snap.json").write_text(json.dumps({"lights": {"kitchen": 75.0}}))
    blackout, backend = make(tmp_path, [FakeLight("kitchen", on=False, brightness=1.0)])
    await blackout.activate()
    await blackout.restore()
    assert ("kitchen", {"on": True, "brightness": 75.0}) in backend.calls


async def test_one_failing_light_does_not_abort_the_rest(tmp_path: Path) -> None:
    blackout, backend = make(
        tmp_path,
        [FakeLight("a", on=True, brightness=10.0), FakeLight("b", on=True, brightness=20.0)],
    )
    backend.fail_ids = {"a"}
    await blackout.activate()
    assert ("b", {"on": False, "brightness": None}) in backend.calls


async def test_second_activate_is_a_noop(tmp_path: Path) -> None:
    blackout, backend = make(tmp_path, [FakeLight("kitchen", on=True, brightness=60.0)])
    await blackout.activate()
    backend.calls.clear()
    await blackout.activate()  # lights are off now; must not re-snapshot them as off
    assert backend.calls == []
    backend.calls.clear()
    await blackout.restore()
    assert backend.calls == [("kitchen", {"on": True, "brightness": 60.0})]


async def test_active_property_tracks_blackout_state(tmp_path: Path) -> None:
    # main.py uses this to suppress white cues while the white bulbs are blacked out.
    blackout, _ = make(tmp_path, [FakeLight("kitchen", on=True, brightness=60.0)])
    assert blackout.active is False
    await blackout.activate()
    assert blackout.active is True
    await blackout.restore()
    assert blackout.active is False


async def test_restore_recovers_orphaned_snapshot_from_prior_process(tmp_path: Path) -> None:
    # Service restarted mid-party: this process never activated, but the file is truth.
    (tmp_path / "snap.json").write_text(json.dumps({"lights": {"white": 90.0}}))
    blackout, backend = make(tmp_path, [FakeLight("white", on=False, brightness=1.0)])
    await blackout.restore()
    assert backend.calls == [("white", {"on": True, "brightness": 90.0})]
    assert not (tmp_path / "snap.json").exists()


async def test_restore_without_snapshot_or_file_is_a_noop(tmp_path: Path) -> None:
    blackout, backend = make(tmp_path, [FakeLight("white", on=True, brightness=50.0)])
    await blackout.restore()
    assert backend.calls == []


async def test_all_lights_on_applies_party_over_scene_to_every_bulb(tmp_path: Path) -> None:
    from hue_party.blackout import all_lights_on

    backend = FakeLights(
        [FakeLight("a", on=False, brightness=5.0), FakeLight("b", on=True, brightness=100.0)]
    )
    backend.fail_ids = {"a"}  # one unreachable bulb must not stop the rest
    await all_lights_on(backend, brightness=80.0, mirek=153)
    assert ("b", {"on": True, "brightness": 80.0, "color_temp": 153}) in backend.calls
