"""One-time link-button pairing with the Hue bridge."""

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from hue_entertainment import HueEntertainmentAPI

DEVICE_TYPE = "hue_party#server"


class _PairingAPI(Protocol):
    async def pair(self, device_type: str = ...) -> dict[str, str]: ...
    async def close(self) -> None: ...


async def pair(
    host: str, api_factory: Callable[[str], _PairingAPI] = HueEntertainmentAPI
) -> dict[str, str]:
    """Run link-button pairing; returns {'username': app_key, 'clientkey': dtls_psk}."""
    api = api_factory(host)
    try:
        return await api.pair(device_type=DEVICE_TYPE)
    finally:
        await api.close()


def write_env(env_path: Path, creds: dict[str, str]) -> None:
    """Upsert HUE_APP_KEY / HUE_CLIENT_KEY into .env, preserving other lines."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    kept = [ln for ln in lines if not ln.startswith(("HUE_APP_KEY=", "HUE_CLIENT_KEY="))]
    kept += [f"HUE_APP_KEY={creds['username']}", f"HUE_CLIENT_KEY={creds['clientkey']}"]
    env_path.write_text("\n".join(kept) + "\n")
