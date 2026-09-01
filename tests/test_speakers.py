from hue_party.speakers import SpeakerControl, SpeakerError

SINKS_OUTPUT = """\
Sink #60
\tState: RUNNING
\tName: raop_sink.Sonos-AAAABBBBCCCC.local.192.168.2.11.7000
\tDescription: Office
\tDriver: PipeWire
\tVolume: front-left: 26214 /  40% / -23.88 dB,   front-right: 26214 /  40% / -23.88 dB
\t        balance 0.00

Sink #66
\tState: RUNNING
\tName: raop_sink.Sonos-DDDDEEEEFFFF.local.192.168.2.24.7000
\tDescription: Sonos Move
\tDriver: PipeWire
\tVolume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
\t        balance 0.00

Sink #78
\tState: SUSPENDED
\tName: raop_sink.MacBook-Pro.local.192.168.2.14.7000
\tDescription: MacBook Pro
\tDriver: PipeWire
\tVolume: front-left: 65536 / 100% / 0.00 dB,   front-right: 65536 / 100% / 0.00 dB
\t        balance 0.00
"""

MODULES_OUTPUT = """\
Module #536870915
\tName: module-loopback
\tArgument: source=music_bus.monitor sink=raop_sink.Sonos-AAAABBBBCCCC.local.192.168.2.11.7000 latency_msec=200
\tUsage counter: n/a

Module #536870920
\tName: module-null-sink
\tArgument: media.class=Audio/Sink sink_name=music_bus channel_map=stereo
\tUsage counter: n/a
"""


def fake_runner(responses: dict[tuple[str, ...], tuple[int, str, str]]):
    calls: list[tuple[str, ...]] = []

    async def run(*args: str) -> tuple[int, str, str]:
        calls.append(args)
        return responses.get(args, (0, "", ""))

    return run, calls


async def test_list_speakers_filters_to_sonos_and_reports_enabled_state() -> None:
    run, _ = fake_runner(
        {
            ("pactl", "list", "sinks"): (0, SINKS_OUTPUT, ""),
            ("pactl", "list", "modules"): (0, MODULES_OUTPUT, ""),
        }
    )
    speakers = await SpeakerControl(runner=run).list_speakers()
    names = {s.description for s in speakers}
    assert names == {"Office", "Sonos Move"}  # MacBook Pro excluded, not a Sonos

    office = next(s for s in speakers if s.description == "Office")
    assert office.enabled is True  # has a loopback module targeting it
    assert office.volume_pct == 40

    move = next(s for s in speakers if s.description == "Sonos Move")
    assert move.enabled is False  # no loopback module targets it
    assert move.volume_pct == 100


async def test_list_speakers_raises_actionable_error_on_pactl_failure() -> None:
    run, _ = fake_runner({("pactl", "list", "sinks"): (1, "", "connection refused")})
    try:
        await SpeakerControl(runner=run).list_speakers()
        raise AssertionError("expected SpeakerError")
    except SpeakerError as exc:
        assert "connection refused" in str(exc)


async def test_enable_loads_loopback_module_with_correct_source_and_sink() -> None:
    run, calls = fake_runner(
        {
            (
                "pactl",
                "load-module",
                "module-loopback",
                "source=music_bus.monitor",
                "sink=raop_sink.Sonos-DDDDEEEEFFFF.local.192.168.2.24.7000",
                "latency_msec=200",
            ): (0, "536870999\n", "")
        }
    )
    await SpeakerControl(runner=run).enable("raop_sink.Sonos-DDDDEEEEFFFF.local.192.168.2.24.7000")
    assert len(calls) == 1


async def test_disable_unloads_the_matching_loopback_module() -> None:
    run, calls = fake_runner(
        {
            ("pactl", "list", "modules"): (0, MODULES_OUTPUT, ""),
            ("pactl", "unload-module", "536870915"): (0, "", ""),
        }
    )
    await SpeakerControl(runner=run).disable("raop_sink.Sonos-AAAABBBBCCCC.local.192.168.2.11.7000")
    assert ("pactl", "unload-module", "536870915") in calls


async def test_disable_is_a_noop_when_not_currently_enabled() -> None:
    run, calls = fake_runner({("pactl", "list", "modules"): (0, MODULES_OUTPUT, "")})
    await SpeakerControl(runner=run).disable("raop_sink.Sonos-DDDDEEEEFFFF.local.192.168.2.24.7000")
    assert not any(c[:2] == ("pactl", "unload-module") for c in calls)


async def test_set_volume_sends_percent() -> None:
    run, calls = fake_runner({})
    await SpeakerControl(runner=run).set_volume(
        "raop_sink.Sonos-AAAABBBBCCCC.local.192.168.2.11.7000", 55
    )
    assert (
        "pactl",
        "set-sink-volume",
        "raop_sink.Sonos-AAAABBBBCCCC.local.192.168.2.11.7000",
        "55%",
    ) in calls


DISCOVER_MODULES_OUTPUT = (
    MODULES_OUTPUT
    + """
Module #536870940
\tName: module-raop-discover
\tArgument:
\tUsage counter: n/a
"""
)

MOVE_SINK = "raop_sink.Sonos-DDDDEEEEFFFF.local.192.168.2.24.7000"
OFFICE_SINK = "raop_sink.Sonos-AAAABBBBCCCC.local.192.168.2.11.7000"


async def noop_sleep(_seconds: float) -> None:
    pass


async def test_rescan_reloads_discovery_and_relinks_missing_loopbacks() -> None:
    run, calls = fake_runner(
        {
            ("pactl", "list", "modules"): (0, DISCOVER_MODULES_OUTPUT, ""),
            ("pactl", "list", "sinks"): (0, SINKS_OUTPUT, ""),
        }
    )
    await SpeakerControl(runner=run, sleeper=noop_sleep).rescan()
    assert ("pactl", "unload-module", "536870940") in calls  # old discovery dropped
    assert ("pactl", "load-module", "module-raop-discover") in calls  # fresh mDNS browse
    # Office already has its loopback; Sonos Move lost it and gets relinked.
    relinks = [c for c in calls if c[:3] == ("pactl", "load-module", "module-loopback")]
    assert len(relinks) == 1 and f"sink={MOVE_SINK}" in relinks[0]


async def test_heal_respects_a_speaker_the_host_turned_off() -> None:
    run, calls = fake_runner(
        {
            ("pactl", "list", "modules"): (0, MODULES_OUTPUT, ""),
            ("pactl", "list", "sinks"): (0, SINKS_OUTPUT, ""),
        }
    )
    control = SpeakerControl(runner=run, sleeper=noop_sleep)
    await control.disable(MOVE_SINK)  # host explicitly turned this speaker off
    await control.heal()
    assert not any(c[:3] == ("pactl", "load-module", "module-loopback") for c in calls)
    await control.enable(MOVE_SINK)  # turning it back on clears the exclusion
    calls.clear()
    await control.heal()
    assert any(
        f"sink={MOVE_SINK}" in c for c in calls if c[1:3] == ("load-module", "module-loopback")
    )


class FakeHealControl:
    def __init__(self, speakers: int) -> None:
        self.speakers = speakers
        self.heals = 0
        self.rescans = 0

    async def list_speakers(self):
        return list(range(self.speakers))

    async def heal(self) -> int:
        self.heals += 1
        return 0

    async def rescan(self) -> None:
        self.rescans += 1


async def test_healer_relinks_when_speakers_present() -> None:
    from hue_party.speakers import SpeakerHealer

    control = FakeHealControl(speakers=2)
    healer = SpeakerHealer(control, empty_rescan_after=2)
    await healer.poll_once()
    assert control.heals == 1
    assert control.rescans == 0


async def test_healer_kicks_discovery_after_consecutive_empty_checks() -> None:
    from hue_party.speakers import SpeakerHealer

    control = FakeHealControl(speakers=0)
    healer = SpeakerHealer(control, empty_rescan_after=2)
    await healer.poll_once()
    assert control.rescans == 0  # one empty check could be a blip
    await healer.poll_once()
    assert control.rescans == 1
    control.speakers = 2
    await healer.poll_once()  # recovery resets the counter
    control.speakers = 0
    await healer.poll_once()
    assert control.rescans == 1


async def test_set_all_volumes_hits_every_sonos_sink_and_survives_failures() -> None:
    run, calls = fake_runner(
        {
            ("pactl", "list", "sinks"): (0, SINKS_OUTPUT, ""),
            ("pactl", "list", "modules"): (0, MODULES_OUTPUT, ""),
            ("pactl", "set-sink-volume", OFFICE_SINK, "70%"): (1, "", "sink gone"),
        }
    )
    control = SpeakerControl(runner=run, sleeper=noop_sleep)
    await control.set_all_volumes(70)
    assert ("pactl", "set-sink-volume", MOVE_SINK, "70%") in calls
    assert ("pactl", "set-sink-volume", OFFICE_SINK, "70%") in calls  # attempted, failed, logged


async def test_missing_pactl_binary_surfaces_as_speaker_error() -> None:
    async def run(*args: str) -> tuple[int, str, str]:
        raise FileNotFoundError(2, "No such file or directory", "pactl")

    import pytest

    with pytest.raises(SpeakerError, match="pactl"):
        await SpeakerControl(runner=run, sleeper=noop_sleep).list_speakers()
