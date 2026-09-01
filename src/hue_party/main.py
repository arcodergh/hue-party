"""CLI entrypoint: pair | test-lights | listen | run."""

import argparse
import asyncio
import logging
import os
import time
from pathlib import Path

import uvicorn
from aiohue import HueBridgeV2
from dotenv import load_dotenv
from hue_entertainment import EntertainmentSession, LightColorCommand

from hue_party.analyzer import AudioAnalyzer
from hue_party.blackout import DEFAULT_SNAPSHOT_PATH, Blackout, all_lights_on
from hue_party.calibrator import (
    DEFAULT_CLICK_PATH,
    Calibrator,
    generate_click,
    measure_beat_latency_ms,
)
from hue_party.config import load_secrets, load_settings
from hue_party.controller import ShowController
from hue_party.delay import DelayBuffer
from hue_party.engine import EffectEngine
from hue_party.history import DEFAULT_HISTORY_PATH, PlayHistory
from hue_party.models import AudioFrame, WhiteCue
from hue_party.music import MusicControl
from hue_party.pairing import pair, write_env
from hue_party.player import PlayerControl, poll_track
from hue_party.preflight import run_preflight
from hue_party.prefs import DEFAULT_PREFS_PATH, Prefs
from hue_party.simulator import SIM_CHANNELS, TerminalRenderer
from hue_party.speakers import SpeakerControl, SpeakerHealer
from hue_party.streamer import LightStreamer, channel_infos, open_session
from hue_party.supervisor import run_supervised
from hue_party.watchdog import StreamWatchdog
from hue_party.web.app import create_app
from hue_party.white import WhiteLights

CONFIG_PATH = Path("config/application.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hue-party", description="Music-reactive Hue party server"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("pair", help="Pair with the Hue bridge (press the link button first)")

    test = sub.add_parser("test-lights", help="Stream a static red to the entertainment area")
    test.add_argument("--seconds", type=int, default=5)

    sub.add_parser("listen", help="Print detected beats/energies from the capture device")

    run = sub.add_parser("run", help="Start the party server")
    run.add_argument("--simulate", action="store_true", help="Render lights in the terminal")

    return parser


async def _cmd_pair() -> None:
    settings = load_settings(CONFIG_PATH)
    print(f"Press the link button on the Hue bridge at {settings.hue.bridge_host} now...")
    creds = await pair(settings.hue.bridge_host)
    write_env(Path(".env"), creds)
    print("Paired. Credentials written to .env — keep that file private.")


async def _cmd_test_lights(seconds: int) -> None:
    settings = load_settings(CONFIG_PATH)
    secrets = load_secrets()
    session, area = await open_session(settings, secrets)
    try:
        print(f"Streaming red to '{area.name}' ({len(area.channels)} channels) for {seconds}s...")
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            session.send(
                [LightColorCommand(channel_id=ch.channel_id, red=65535) for ch in area.channels]
            )
            await asyncio.sleep(1 / 50)
    finally:
        await session.aclose()
    print("Done — lights should return to their previous state.")


async def _cmd_listen() -> None:
    settings = load_settings(CONFIG_PATH)

    def show(frame: AudioFrame) -> None:
        if frame.is_beat:
            print(
                f"BEAT  bpm={frame.tempo_bpm:5.1f} vol={frame.volume:.2f} "
                f"low={frame.low:.2f} mid={frame.mid:.2f} high={frame.high:.2f}"
            )

    analyzer = AudioAnalyzer(settings.audio, show)
    await analyzer.run()


async def _run_show(simulate: bool) -> None:
    settings = load_settings(CONFIG_PATH)
    status: dict[str, str] = {}
    player = PlayerControl()
    watchdog: StreamWatchdog | None = None
    whites: WhiteLights | None = None
    white_bridge: HueBridgeV2 | None = None
    blackout: Blackout | None = None

    if not simulate:
        checks = await run_preflight(settings)
        for check in checks:
            marker = "OK " if check.ok else "FAIL"
            print(f"[{marker}] {check.name}" + (f" — {check.hint}" if check.hint else ""))
        if not all(c.ok for c in checks):
            raise SystemExit("Preflight failed — fix the items above and retry.")

    if simulate:
        channels = SIM_CHANNELS
        sink: TerminalRenderer | LightStreamer = TerminalRenderer([c.channel_id for c in channels])
        session = None
    else:
        secrets = load_secrets()
        session, area = await open_session(settings, secrets)
        channels = channel_infos(area)

        async def reconnect() -> EntertainmentSession:
            nonlocal session
            assert session is not None  # only defined in this (non-simulate) branch
            await session.aclose()
            session, _ = await open_session(settings, secrets)
            return session

        async def remote_status() -> tuple[str, str]:
            assert session is not None
            return await session.remote_status()

        async def stop_stream() -> None:
            assert session is not None
            await session.stop()

        sink = LightStreamer(session, DelayBuffer(), reconnect=reconnect)
        sink.offset_ms = settings.show.default_offset_ms

        if settings.hue.white_light_ids or settings.hue.blackout_others:
            white_bridge = HueBridgeV2(settings.hue.bridge_host, secrets.hue_app_key)
            await white_bridge.initialize()
        if white_bridge is not None and settings.hue.white_light_ids:
            whites = WhiteLights(
                white_bridge.lights,
                settings.hue.white_light_ids,
                settings.hue.white_min_interval_s,
            )
        if white_bridge is not None and settings.hue.blackout_others:
            area_config = white_bridge.config.entertainment_configuration.get(area.id)
            party_ids = {ref.rid for ref in (getattr(area_config, "light_services", None) or [])}
            if party_ids:
                blackout = Blackout(
                    white_bridge.lights,
                    exclude_ids=party_ids,
                    snapshot_path=DEFAULT_SNAPSHOT_PATH.expanduser(),
                )
            else:
                print("WARN: could not resolve party light ids; blackout disabled")

        watchdog = StreamWatchdog(
            player_status=player.status,
            remote_status=remote_status,
            reclaim=sink.reconnect_now,
            suspend=stop_stream,
            on_party_start=blackout.activate if blackout is not None else None,
            on_party_stop=blackout.restore if blackout is not None else None,
            # late binding: engine is assigned below, before any watchdog poll runs
            stream_required=lambda: engine.mode == "calibration",
            status=status,
            poll_s=settings.hue.watchdog_poll_s,
            music_stop_grace_s=settings.hue.music_stop_grace_s,
        )

    engine = EffectEngine(channels, settings.show)
    pending: set[asyncio.Task[None]] = set()

    async def _white_later(cue: WhiteCue, delay_s: float) -> None:
        await asyncio.sleep(delay_s)
        assert whites is not None
        await whites.apply(cue)

    def on_frame(frame: AudioFrame) -> None:
        if engine.mode == "calibration":
            return  # the calibrator drives clicks and flashes deterministically
        light_frame = engine.render(frame)
        sink.submit(light_frame)
        if blackout is not None and blackout.active and not engine.panic:
            return  # white bulbs are deliberately off during the party; no cues
        if light_frame.white is not None and whites is not None:
            offset_s = (sink.offset_ms if isinstance(sink, LightStreamer) else 0) / 1000
            task = asyncio.create_task(_white_later(light_frame.white, offset_s))
            pending.add(task)
            task.add_done_callback(pending.discard)

    analyzer = AudioAnalyzer(settings.audio, on_frame)

    click_path = DEFAULT_CLICK_PATH.expanduser()
    generate_click(click_path)

    async def play_click() -> None:
        proc = await asyncio.create_subprocess_exec(
            "paplay",
            "-d",
            "music_bus",
            str(click_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()

    def submit_flash(at: float) -> None:
        beat = AudioFrame(
            timestamp=at, is_beat=True, is_onset=True,
            tempo_bpm=60.0, volume=0.8, low=0.8, mid=0.5, high=0.5,
        )  # fmt: skip
        sink.submit(engine.render(beat))
        dark = AudioFrame(
            timestamp=at + 0.15, is_beat=False, is_onset=False,
            tempo_bpm=60.0, volume=0.0, low=0.0, mid=0.0, high=0.0,
        )  # fmt: skip
        sink.submit(engine.render(dark))

    calibrator = Calibrator(
        measure=lambda name: asyncio.to_thread(measure_beat_latency_ms, name, settings.audio),
        active_engine=lambda: analyzer.beat_engine,
        play_click=play_click,
        submit_flash=submit_flash,
    )

    # Host-tuned settings from previous sessions win over the yaml baseline;
    # anything invalid (renamed mode, uninstalled engine) falls back with a note.
    prefs = Prefs(DEFAULT_PREFS_PATH.expanduser())
    if isinstance(sink, LightStreamer):
        sink.offset_ms = int(prefs.get("offset_ms", settings.show.default_offset_ms))
    engine.brightness_cap = float(prefs.get("brightness_cap", settings.show.brightness_cap))
    for apply_pref, key, fallback in (
        (engine.set_mode, "mode", settings.show.default_mode),
        (engine.set_palette, "palette", settings.show.default_palette),
        (analyzer.set_beat_engine, "beat_engine", settings.audio.beat_engine),
    ):
        try:
            apply_pref(str(prefs.get(key, fallback)))
        except ValueError:
            print(f"WARN: saved {key} {prefs.get(key, fallback)!r} unavailable; using default")

    speakers = SpeakerControl()
    controller = ShowController(
        engine,
        streamer=sink if isinstance(sink, LightStreamer) else None,
        speakers=speakers,
        music=MusicControl(
            browser=settings.music.browser,
            debug_port=settings.music.debug_port,
            profile_dir=settings.music.profile_dir,
        ),
        analyzer=analyzer,
        watchdog=watchdog,
        party_over=(
            None
            if white_bridge is None
            else lambda: all_lights_on(
                white_bridge.lights,
                brightness=settings.hue.stop_scene_brightness,
                mirek=settings.hue.stop_scene_mirek,
            )
        ),
        history=PlayHistory(DEFAULT_HISTORY_PATH.expanduser()),
        calibrator=calibrator,
        prefs=prefs,
        status=status,
    )
    controller.player = player

    def restart_service() -> None:
        # Hard-exit shortly after the response flushes; systemd's Restart=on-failure
        # brings the service back. Cleanup is crash-safe by design (blackout snapshot).
        print("Restart requested from the UI; exiting for systemd to relaunch...")
        asyncio.get_running_loop().call_later(0.7, os._exit, 1)

    web_app = create_app(controller, restarter=restart_service)
    server = uvicorn.Server(
        uvicorn.Config(web_app, host=settings.web.host, port=settings.web.port, log_level="warning")
    )

    tasks = [asyncio.create_task(run_supervised("analyzer", analyzer.run, status))]
    if isinstance(sink, LightStreamer):
        tasks.append(asyncio.create_task(run_supervised("streamer", sink.run, status)))
    if watchdog is not None:
        tasks.append(asyncio.create_task(run_supervised("watchdog", watchdog.run, status)))
    if not simulate:
        healer = SpeakerHealer(speakers)
        tasks.append(asyncio.create_task(run_supervised("speakers", healer.run, status)))
    tasks.append(asyncio.create_task(run_supervised("web", server.serve, status)))
    tasks.append(
        asyncio.create_task(
            run_supervised("player", lambda: poll_track(controller, controller.player), status)
        )
    )
    print(f"Host UI:  http://<this-box>:{settings.web.port}/")
    print(f"Guests:   http://<this-box>:{settings.web.port}/guest")
    try:
        await asyncio.gather(*tasks)
    finally:
        if blackout is not None:
            await blackout.restore()  # give the room its lights back on shutdown
        if session is not None:
            await session.aclose()
        if white_bridge is not None:
            await white_bridge.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    load_dotenv()
    args = build_parser().parse_args()
    if args.command == "pair":
        asyncio.run(_cmd_pair())
    elif args.command == "test-lights":
        asyncio.run(_cmd_test_lights(args.seconds))
    elif args.command == "listen":
        asyncio.run(_cmd_listen())
    elif args.command == "run":
        asyncio.run(_run_show(args.simulate))


if __name__ == "__main__":
    main()
