import json
from pathlib import Path

from hue_party.prefs import Prefs


def test_set_and_get_round_trip_across_instances(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    prefs = Prefs(path)
    prefs.set("offset_ms", 1450)
    prefs.set("brightness_cap", 0.7)
    reloaded = Prefs(path)
    assert reloaded.get("offset_ms", 1200) == 1450
    assert reloaded.get("brightness_cap", 1.0) == 0.7


def test_get_falls_back_to_default_when_unset(tmp_path: Path) -> None:
    prefs = Prefs(tmp_path / "settings.json")
    assert prefs.get("offset_ms", 1200) == 1200


def test_corrupt_file_starts_fresh_and_recovers(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{broken")
    prefs = Prefs(path)
    assert prefs.get("mode", "beat_flash") == "beat_flash"
    prefs.set("mode", "pulse_run")
    assert json.loads(path.read_text())["mode"] == "pulse_run"
