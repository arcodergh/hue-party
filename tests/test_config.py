from pathlib import Path

import pytest

from hue_party.config import load_secrets, load_settings
from hue_party.models import ChannelColor

YAML = """\
hue:
  bridge_host: "192.168.1.50"
  white_light_ids: ["abc-123"]
show:
  default_offset_ms: 800
"""


def test_load_settings_defaults_and_overrides(tmp_path: Path) -> None:
    p = tmp_path / "application.yaml"
    p.write_text(YAML)
    s = load_settings(p)
    assert s.hue.bridge_host == "192.168.1.50"
    assert s.hue.white_light_ids == ["abc-123"]
    assert s.show.default_offset_ms == 800
    assert s.audio.sample_rate == 44100  # default
    assert s.web.port == 8000  # default


def test_load_secrets_reads_env() -> None:
    s = load_secrets({"HUE_APP_KEY": "appkey", "HUE_CLIENT_KEY": "c" * 32})
    assert s.hue_app_key == "appkey"
    assert s.hue_client_key == "c" * 32


def test_load_secrets_missing_is_actionable() -> None:
    with pytest.raises(RuntimeError, match="hue-party pair"):
        load_secrets({})


def test_channel_color_is_immutable() -> None:
    c = ChannelColor(1, 2, 3)
    with pytest.raises(AttributeError):
        c.red = 9  # type: ignore[misc]
