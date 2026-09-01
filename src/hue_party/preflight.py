"""Startup checks with actionable hints. Hard failures stop the show before it starts."""

import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass

from hue_party.config import Settings


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    hint: str = ""


def check_music_bus(pactl_sinks_output: str) -> Check:
    names = {line.split("\t")[1] for line in pactl_sinks_output.splitlines() if "\t" in line}
    if "music_bus" in names:
        return Check("music_bus sink", True)
    return Check(
        "music_bus sink",
        False,
        "Virtual sink missing — run scripts/setup-audio.sh, then route Chrome to 'music_bus'.",
    )


def check_secrets(env: Mapping[str, str]) -> Check:
    if env.get("HUE_APP_KEY") and env.get("HUE_CLIENT_KEY"):
        return Check("hue credentials", True)
    return Check("hue credentials", False, "Missing — run 'uv run hue-party pair'.")


async def run_preflight(settings: Settings) -> list[Check]:
    checks = [check_secrets(os.environ)]
    try:
        proc = await asyncio.create_subprocess_exec(
            "pactl", "list", "short", "sinks", stdout=asyncio.subprocess.PIPE
        )
        out, _ = await proc.communicate()
        checks.append(check_music_bus(out.decode()))
    except FileNotFoundError:
        checks.append(Check("music_bus sink", False, "pactl not found — is PipeWire installed?"))
    return checks
