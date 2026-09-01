"""Per-speaker AirPlay routing and volume, via PipeWire's pactl.

Each discovered Sonos speaker shows up as a `raop_sink.Sonos-*` PipeWire sink as
soon as `module-raop-discover` finds it over mDNS — regardless of whether music
is actually routed to it. A speaker only receives audio once a `module-loopback`
links `music_bus.monitor` to that sink; this module lets the host toggle that
link and each speaker's own output volume from the web UI instead of the shell.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

Runner = Callable[..., Awaitable[tuple[int, str, str]]]
Sleeper = Callable[[float], Awaitable[None]]

SONOS_SINK_PREFIX = "raop_sink.Sonos-"
RAOP_SETTLE_S = 4.0  # give a fresh mDNS browse time to surface the speakers
HEAL_INTERVAL_S = 30.0


class SpeakerError(RuntimeError):
    pass


async def _exec(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


@dataclass(frozen=True, slots=True)
class Speaker:
    sink_name: str
    description: str
    enabled: bool
    volume_pct: int


def _parse_sonos_sinks(pactl_list_sinks_output: str) -> dict[str, str]:
    """sink_name -> description, for Sonos sinks only."""
    sinks: dict[str, str] = {}
    name: str | None = None
    for line in pactl_list_sinks_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name: "):
            name = stripped.removeprefix("Name: ")
        elif stripped.startswith("Description: ") and name is not None:
            if name.startswith(SONOS_SINK_PREFIX):
                sinks[name] = stripped.removeprefix("Description: ")
            name = None
    return sinks


def _parse_sink_volumes(pactl_list_sinks_output: str) -> dict[str, int]:
    """sink_name -> volume percent (front-left), for every sink present."""
    volumes: dict[str, int] = {}
    name: str | None = None
    for line in pactl_list_sinks_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name: "):
            name = stripped.removeprefix("Name: ")
        elif stripped.startswith("Volume: ") and name is not None:
            match = re.search(r"(\d+)%", stripped)
            if match:
                volumes[name] = int(match.group(1))
            name = None
    return volumes


def _parse_loopback_targets(pactl_list_modules_output: str) -> set[str]:
    """sink names currently fed by a music_bus loopback."""
    targets: set[str] = set()
    is_loopback = False
    for line in pactl_list_modules_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Name: "):
            is_loopback = stripped == "Name: module-loopback"
        elif is_loopback and stripped.startswith("Argument: "):
            match = re.search(r"sink=(\S+)", stripped)
            if match:
                targets.add(match.group(1))
            is_loopback = False
    return targets


class SpeakerControl:
    def __init__(
        self,
        source: str = "music_bus.monitor",
        runner: Runner = _exec,
        sleeper: Sleeper = asyncio.sleep,
    ) -> None:
        self._source = source
        self._run = runner
        self._sleep = sleeper
        self._user_disabled: set[str] = set()  # heal must not undo a deliberate off

    async def _pactl(self, *args: str) -> tuple[int, str, str]:
        try:
            return await self._run(*args)
        except OSError as exc:  # binary missing (e.g. dev box without pulseaudio-utils)
            raise SpeakerError(f"pactl not available: {exc}") from exc

    async def list_speakers(self) -> list[Speaker]:
        rc_sinks, sinks_out, err = await self._pactl("pactl", "list", "sinks")
        if rc_sinks != 0:
            raise SpeakerError(f"pactl list sinks failed: {err.strip() or rc_sinks}")
        rc_modules, modules_out, err = await self._pactl("pactl", "list", "modules")
        if rc_modules != 0:
            raise SpeakerError(f"pactl list modules failed: {err.strip() or rc_modules}")

        descriptions = _parse_sonos_sinks(sinks_out)
        volumes = _parse_sink_volumes(sinks_out)
        enabled = _parse_loopback_targets(modules_out)
        return [
            Speaker(
                sink_name=name,
                description=description,
                enabled=name in enabled,
                volume_pct=volumes.get(name, 100),
            )
            for name, description in sorted(descriptions.items(), key=lambda kv: kv[1])
        ]

    async def rescan(self) -> None:
        """Force a fresh mDNS browse: reload RAOP discovery, then relink loopbacks."""
        rc, out, err = await self._pactl("pactl", "list", "modules")
        if rc != 0:
            raise SpeakerError(f"pactl list modules failed: {err.strip() or rc}")
        for module_id in _find_module_ids(out, "module-raop-discover"):
            await self._pactl("pactl", "unload-module", module_id)
        rc, _, err = await self._pactl("pactl", "load-module", "module-raop-discover")
        if rc != 0:
            raise SpeakerError(f"failed to reload RAOP discovery: {err.strip() or rc}")
        await self._sleep(RAOP_SETTLE_S)
        await self.heal()

    async def heal(self) -> int:
        """Relink loopbacks to Sonos sinks that lost theirs; returns how many."""
        relinked = 0
        for speaker in await self.list_speakers():
            if speaker.enabled or speaker.sink_name in self._user_disabled:
                continue
            try:
                await self.enable(speaker.sink_name)
                relinked += 1
                log.info("relinked audio to %s", speaker.description)
            except SpeakerError:
                log.warning("could not relink %s", speaker.description, exc_info=True)
        return relinked

    async def enable(self, sink_name: str) -> None:
        self._user_disabled.discard(sink_name)
        rc, _, err = await self._pactl(
            "pactl",
            "load-module",
            "module-loopback",
            f"source={self._source}",
            f"sink={sink_name}",
            "latency_msec=200",
        )
        if rc != 0:
            raise SpeakerError(f"failed to enable {sink_name}: {err.strip() or rc}")

    async def disable(self, sink_name: str) -> None:
        self._user_disabled.add(sink_name)
        rc, out, err = await self._pactl("pactl", "list", "modules")
        if rc != 0:
            raise SpeakerError(f"pactl list modules failed: {err.strip() or rc}")
        module_id = _find_loopback_module_id(out, sink_name)
        if module_id is None:
            return
        rc, _, err = await self._pactl("pactl", "unload-module", module_id)
        if rc != 0:
            raise SpeakerError(f"failed to disable {sink_name}: {err.strip() or rc}")

    async def set_all_volumes(self, pct: int) -> None:
        """Master volume: set every Sonos speaker to the same level."""
        failures = 0
        for speaker in await self.list_speakers():
            try:
                await self.set_volume(speaker.sink_name, pct)
            except SpeakerError:
                failures += 1
                log.warning("master volume failed for %s", speaker.description, exc_info=True)
        if failures:
            log.info("master volume applied with %d failures", failures)

    async def set_volume(self, sink_name: str, pct: int) -> None:
        rc, _, err = await self._pactl("pactl", "set-sink-volume", sink_name, f"{pct}%")
        if rc != 0:
            raise SpeakerError(f"failed to set volume for {sink_name}: {err.strip() or rc}")


class SpeakerHealer:
    """Periodic self-heal: relink flapped speakers; kick mDNS discovery when all vanish."""

    def __init__(self, control: SpeakerControl, *, empty_rescan_after: int = 2) -> None:
        self._control = control
        self._empty_rescan_after = empty_rescan_after
        self._empty_checks = 0

    async def poll_once(self) -> None:
        if await self._control.list_speakers():
            self._empty_checks = 0
            await self._control.heal()
            return
        self._empty_checks += 1
        if self._empty_checks >= self._empty_rescan_after:
            log.warning("no Sonos sinks for %d checks; kicking mDNS discovery", self._empty_checks)
            await self._control.rescan()
            self._empty_checks = 0

    async def run(self, interval_s: float = HEAL_INTERVAL_S) -> None:
        while True:
            try:
                await self.poll_once()
            except Exception:
                log.warning("speaker heal pass failed; retrying", exc_info=True)
            await asyncio.sleep(interval_s)


def _find_module_ids(pactl_list_modules_output: str, module_name: str) -> list[str]:
    ids: list[str] = []
    module_id: str | None = None
    for line in pactl_list_modules_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Module #"):
            module_id = stripped.removeprefix("Module #")
        elif stripped == f"Name: {module_name}" and module_id is not None:
            ids.append(module_id)
    return ids


def _find_loopback_module_id(pactl_list_modules_output: str, sink_name: str) -> str | None:
    module_id: str | None = None
    is_loopback = False
    for line in pactl_list_modules_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Module #"):
            module_id = stripped.removeprefix("Module #")
        elif stripped.startswith("Name: "):
            is_loopback = stripped == "Name: module-loopback"
        elif is_loopback and stripped.startswith("Argument: ") and f"sink={sink_name}" in stripped:
            return module_id
    return None
