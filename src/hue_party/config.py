"""Settings (versioned yaml) and Secrets (environment) loading."""

import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import BaseModel

from hue_party.watchdog import DEFAULT_MUSIC_STOP_GRACE_S, DEFAULT_POLL_S


class HueConfig(BaseModel):
    bridge_host: str
    entertainment_area: str = ""
    white_light_ids: list[str] = []
    white_min_interval_s: float = 0.5
    watchdog_poll_s: float = DEFAULT_POLL_S
    music_stop_grace_s: float = DEFAULT_MUSIC_STOP_GRACE_S
    blackout_others: bool = True
    stop_scene_brightness: float = 80.0  # party-over scene: percent brightness
    stop_scene_mirek: int = 153  # party-over scene: color temp (153 = coolest white)


class AudioConfig(BaseModel):
    device: str = "music_bus.monitor"
    sample_rate: int = 44100
    fps: int = 60
    fft_size: int = 4096
    beat_engine: str = "classic"


class ShowConfig(BaseModel):
    default_mode: str = "beat_flash"
    default_palette: str = "fiesta"
    default_offset_ms: int = 1000
    brightness_cap: float = 1.0
    strobe_max_hz: float = 8.0
    drop_duration_s: float = 5.0


class MusicConfig(BaseModel):
    browser: str = "google-chrome"
    debug_port: int = 9222
    profile_dir: str = "~/.config/hue-party/chrome-profile"


class WebConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class Settings(BaseModel):
    hue: HueConfig
    audio: AudioConfig = AudioConfig()
    show: ShowConfig = ShowConfig()
    music: MusicConfig = MusicConfig()
    web: WebConfig = WebConfig()


class Secrets(BaseModel):
    hue_app_key: str
    hue_client_key: str


def load_settings(path: Path) -> Settings:
    """Load and validate application.yaml."""
    with path.open() as f:
        return Settings.model_validate(yaml.safe_load(f))


def load_secrets(env: Mapping[str, str] | None = None) -> Secrets:
    """Read Hue credentials from the environment (.env is loaded by the entrypoint)."""
    e = os.environ if env is None else env
    try:
        return Secrets(hue_app_key=e["HUE_APP_KEY"], hue_client_key=e["HUE_CLIENT_KEY"])
    except KeyError as exc:
        raise RuntimeError(
            f"Missing environment variable {exc}. Copy .env.example to .env and run "
            "'uv run hue-party pair' to obtain Hue credentials."
        ) from exc
