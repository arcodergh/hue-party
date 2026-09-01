from pathlib import Path

from conftest import CHANNELS
from fastapi.testclient import TestClient

from hue_party.config import ShowConfig
from hue_party.controller import ShowController
from hue_party.engine import EffectEngine
from hue_party.music import MusicControl
from hue_party.speakers import SpeakerControl
from hue_party.web.app import create_app


class FakePlayer:
    def __init__(self, art_url: str | None = None) -> None:
        self._art_url = art_url
        self.stops = 0
        self.pauses = 0
        self.plays = 0

    async def stop(self) -> None:
        self.stops += 1

    async def pause(self) -> None:
        self.pauses += 1

    async def play(self) -> None:
        self.plays += 1

    async def play_pause(self) -> None:
        pass

    async def next_track(self) -> None:
        pass

    async def previous_track(self) -> None:
        pass

    async def now_playing(self) -> str | None:
        return None

    async def art_url(self) -> str | None:
        return self._art_url


class FakeAnalyzer:
    def __init__(self) -> None:
        self.beat_engine = "classic"
        self.beat_engines = ["classic", "predictive"]

    def set_beat_engine(self, name: str) -> None:
        if name not in self.beat_engines:
            raise ValueError(f"Unknown beat engine '{name}'")
        self.beat_engine = name


class FakeWatchdog:
    def __init__(self) -> None:
        self.party_stops = 0
        self.polls = 0

    async def stop_party(self) -> None:
        self.party_stops += 1

    async def poll_once(self) -> None:
        self.polls += 1


def make_client(
    player: FakePlayer | None = None,
    speakers: SpeakerControl | None = None,
    music: MusicControl | None = None,
    analyzer: FakeAnalyzer | None = None,
    watchdog: FakeWatchdog | None = None,
    party_over=None,
    history=None,
    calibrator=None,
    prefs=None,
    restarter=None,
) -> TestClient:
    engine = EffectEngine(CHANNELS, ShowConfig())
    controller = ShowController(
        engine,
        player=player,
        speakers=speakers,
        music=music,
        analyzer=analyzer,
        watchdog=watchdog,
        party_over=party_over,
        history=history,
        calibrator=calibrator,
        prefs=prefs,
        clock=lambda: 100.0,
    )
    return TestClient(create_app(controller, restarter=restarter))


def test_state_reports_modes_and_defaults() -> None:
    client = make_client()
    state = client.get("/api/state").json()
    assert state["mode"] == "beat_flash"
    assert "calibration" not in state["modes"]  # calibration gets its own UI section
    assert state["calibration"] is False
    assert state["palette"] == "fiesta"
    assert state["panic"] is False


def test_calibration_toggle_remembers_and_restores_mode() -> None:
    client = make_client()
    client.post("/api/mode", json={"mode": "bass_pump"})
    assert client.post("/api/calibration", json={"on": True}).status_code == 200
    state = client.get("/api/state").json()
    assert state["mode"] == "calibration"
    assert state["calibration"] is True
    client.post("/api/calibration", json={"on": False})
    state = client.get("/api/state").json()
    assert state["mode"] == "bass_pump"
    assert state["calibration"] is False


def test_calibration_double_on_still_restores_original_mode() -> None:
    client = make_client()
    client.post("/api/mode", json={"mode": "color_wave"})
    client.post("/api/calibration", json={"on": True})
    client.post("/api/calibration", json={"on": True})
    client.post("/api/calibration", json={"on": False})
    assert client.get("/api/state").json()["mode"] == "color_wave"


def test_party_stop_silences_player_ends_party_and_raises_house_lights() -> None:
    player, watchdog = FakePlayer(), FakeWatchdog()
    scenes = 0

    async def party_over() -> None:
        nonlocal scenes
        scenes += 1

    client = make_client(player=player, watchdog=watchdog, party_over=party_over)
    assert client.post("/api/party/stop").status_code == 200
    assert player.stops == 1
    assert watchdog.party_stops == 1
    assert scenes == 1


def test_party_stop_works_without_player_or_watchdog() -> None:
    # Simulate mode has neither; the endpoint must still answer.
    assert make_client().post("/api/party/stop").status_code == 200


def test_beat_engine_listed_and_switchable() -> None:
    client = make_client(analyzer=FakeAnalyzer())
    state = client.get("/api/state").json()
    assert state["beat_engine"] == "classic"
    assert state["beat_engines"] == ["classic", "predictive"]
    assert client.post("/api/beat_engine", json={"engine": "predictive"}).status_code == 200
    assert client.get("/api/state").json()["beat_engine"] == "predictive"
    assert client.post("/api/beat_engine", json={"engine": "vibes"}).status_code == 400


def test_beat_engine_absent_without_analyzer() -> None:
    client = make_client()
    assert "beat_engines" not in client.get("/api/state").json()
    assert client.post("/api/beat_engine", json={"engine": "classic"}).status_code == 503


def test_calibration_off_when_never_on_is_a_noop() -> None:
    client = make_client()
    client.post("/api/calibration", json={"on": False})
    assert client.get("/api/state").json()["mode"] == "beat_flash"


def test_set_mode_roundtrip_and_validation() -> None:
    client = make_client()
    assert client.post("/api/mode", json={"mode": "calibration"}).status_code == 200
    assert client.get("/api/state").json()["mode"] == "calibration"
    assert client.post("/api/mode", json={"mode": "nope"}).status_code == 400


def test_offset_is_range_validated() -> None:
    client = make_client()
    assert client.post("/api/offset", json={"offset_ms": 1500}).status_code == 200
    assert client.post("/api/offset", json={"offset_ms": 9999}).status_code == 422


def test_guest_vote_moves_crowd_strength() -> None:
    client = make_client()
    assert client.get("/api/state").json()["crowd"]["strength"] == 0.0
    for _ in range(4):
        assert client.post("/api/guest/vote", json={"hue": 0.33}).status_code == 200
    assert client.get("/api/state").json()["crowd"]["strength"] > 0.5


def test_panic_and_drop_endpoints() -> None:
    client = make_client()
    assert client.post("/api/panic", json={"on": True}).status_code == 200
    assert client.get("/api/state").json()["panic"] is True
    assert client.post("/api/drop/start").status_code == 200
    drop = client.get("/api/state").json()["drop"]
    assert drop["active"] is True
    assert drop["duration_s"] == 5.0


def test_player_endpoint_without_player_is_503() -> None:
    client = make_client()
    assert client.post("/api/player/play_pause").status_code == 503


SPEAKER_SINKS_OUTPUT = """\
Sink #60
\tName: raop_sink.Sonos-AAA.local.192.168.2.11.7000
\tDescription: Office
\tVolume: front-left: 26214 /  40% / -23.88 dB,   front-right: 26214 /  40% / -23.88 dB
"""

SPEAKER_MODULES_OUTPUT = """\
Module #100
\tName: module-loopback
\tArgument: source=music_bus.monitor sink=raop_sink.Sonos-AAA.local.192.168.2.11.7000 latency_msec=200
"""


def make_speaker_control() -> SpeakerControl:
    async def run(*args: str) -> tuple[int, str, str]:
        if args == ("pactl", "list", "sinks"):
            return (0, SPEAKER_SINKS_OUTPUT, "")
        if args == ("pactl", "list", "modules"):
            return (0, SPEAKER_MODULES_OUTPUT, "")
        return (0, "", "")

    async def no_sleep(_s: float) -> None:
        pass

    return SpeakerControl(runner=run, sleeper=no_sleep)


def test_speakers_endpoints_without_control_are_503() -> None:
    client = make_client()
    assert client.get("/api/speakers").status_code == 503
    assert (
        client.post("/api/speakers/toggle", json={"sink": "x", "enabled": True}).status_code == 503
    )
    assert client.post("/api/speakers/volume", json={"sink": "x", "pct": 50}).status_code == 503


def test_speakers_list_and_controls() -> None:
    client = make_client(speakers=make_speaker_control())
    listed = client.get("/api/speakers").json()
    assert listed == [
        {
            "sink": "raop_sink.Sonos-AAA.local.192.168.2.11.7000",
            "name": "Office",
            "enabled": True,
            "volume_pct": 40,
        }
    ]
    toggle = {"sink": "raop_sink.Sonos-AAA.local.192.168.2.11.7000", "enabled": False}
    assert client.post("/api/speakers/toggle", json=toggle).status_code == 200
    volume = {"sink": "raop_sink.Sonos-AAA.local.192.168.2.11.7000", "pct": 55}
    assert client.post("/api/speakers/volume", json=volume).status_code == 200
    assert client.post("/api/speakers/volume", json={"sink": "x", "pct": 150}).status_code == 422


def test_speakers_rescan_endpoint() -> None:
    assert make_client().post("/api/speakers/rescan").status_code == 503
    client = make_client(speakers=make_speaker_control())
    assert client.post("/api/speakers/rescan").json() == {"ok": "rescanned"}


def test_art_without_player_is_503() -> None:
    client = make_client()
    assert client.get("/api/art").status_code == 503


def test_art_without_available_art_is_404() -> None:
    client = make_client(FakePlayer(art_url=None))
    assert client.get("/api/art").status_code == 404


def test_art_serves_real_png_file(tmp_path: Path) -> None:
    png = tmp_path / "cover.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"fake-rest-of-file")
    client = make_client(FakePlayer(art_url=f"file://{png}"))
    resp = client.get("/api/art")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content == png.read_bytes()


class FakeYT:
    def search(self, query: str, filter: str, limit: int) -> list[dict[str, object]]:
        return [{"videoId": "vid1", "title": "Song", "artists": [{"name": "A"}]}]


def make_music() -> tuple[MusicControl, list[tuple[str, str]]]:
    cdp_calls: list[tuple[str, str]] = []

    async def run(*args: str) -> tuple[int, str, str]:
        return (0, "", "")

    async def cdp(method: str, path: str) -> tuple[int, object]:
        cdp_calls.append((method, path))
        if path == "/json/version":
            return 200, {}
        if path == "/json/list":
            return 200, []
        if path.startswith("/json/new"):
            return 200, {"id": "tab1"}
        return 200, None

    music = MusicControl(browser="google-chrome", runner=run, search_client=FakeYT())
    music._cdp = cdp  # type: ignore[method-assign]
    return music, cdp_calls


def test_music_endpoints_without_control_are_503() -> None:
    client = make_client()
    assert client.get("/api/music/search?q=x").status_code == 503
    assert client.post("/api/music/play", json={"video_id": "abc12"}).status_code == 503


def test_music_search_and_play() -> None:
    music, cdp_calls = make_music()
    client = make_client(music=music)
    results = client.get("/api/music/search?q=daft").json()
    assert results[0]["video_id"] == "vid1"

    assert client.post("/api/music/play", json={"video_id": "vid12"}).status_code == 200
    assert any("music.youtube.com/watch?v=vid12" in path for _, path in cdp_calls)

    bad = client.post("/api/music/play", json={"url": "https://evil.example.com/x"})
    assert bad.status_code == 400
    assert client.post("/api/music/play", json={}).status_code == 422


def test_play_records_history_and_history_endpoint_serves_it(tmp_path: Path) -> None:
    from hue_party.history import PlayHistory

    music, _ = make_music()
    history = PlayHistory(tmp_path / "history.json")
    client = make_client(music=music, history=history)
    body = {"video_id": "vid12", "title": "One More Time", "artist": "Daft Punk", "thumb": "t.jpg"}
    assert client.post("/api/music/play", json=body).status_code == 200
    served = client.get("/api/music/history").json()
    assert served["tracks"][0]["id"] == "vid12"
    assert served["tracks"][0]["title"] == "One More Time"
    assert served["tracks"][0]["artist"] == "Daft Punk"
    assert served["lists"] == []


def test_history_endpoint_is_empty_without_store() -> None:
    assert make_client().get("/api/music/history").json() == {"tracks": [], "lists": []}


def test_ui_files_are_served_with_revalidation_cache_control() -> None:
    # Phones heuristic-cache statics without this, showing stale UI after deploys.
    client = make_client()
    for path in ("/", "/guest", "/static/app.js"):
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_html_references_statics_with_content_versioned_urls() -> None:
    # A changed file gets a changed URL, so browsers can never pair old JS with new HTML.
    import re

    client = make_client()
    for page, script in (("/", "app.js"), ("/guest", "guest.js")):
        html = client.get(page).text
        assert re.search(rf"/static/{re.escape(script)}\?v=[0-9a-f]{{8}}", html), page
        assert re.search(r"/static/style\.css\?v=[0-9a-f]{8}", html), page


def test_calibration_toggle_drives_calibrator_and_pauses_music() -> None:
    class FakeCalibrator:
        def __init__(self) -> None:
            self.starts = 0
            self.stops = 0

        def start(self) -> None:
            self.starts += 1

        def stop(self) -> None:
            self.stops += 1

    player, calibrator, watchdog = FakePlayer(), FakeCalibrator(), FakeWatchdog()
    client = make_client(player=player, calibrator=calibrator, watchdog=watchdog)
    client.post("/api/calibration", json={"on": True})
    assert calibrator.starts == 1
    assert player.pauses == 1
    assert watchdog.polls == 1  # stream reclaimed immediately, not on the next poll
    client.post("/api/calibration", json={"on": False})
    assert calibrator.stops == 1
    assert player.plays == 1


def test_ui_tweaks_persist_to_prefs(tmp_path: Path) -> None:
    from hue_party.prefs import Prefs

    prefs = Prefs(tmp_path / "settings.json")
    client = make_client(analyzer=FakeAnalyzer(), prefs=prefs)
    client.post("/api/offset", json={"offset_ms": 1450})
    client.post("/api/brightness", json={"cap": 0.7})
    client.post("/api/mode", json={"mode": "bass_pump"})
    client.post("/api/palette", json={"palette": "ice"})
    client.post("/api/beat_engine", json={"engine": "predictive"})
    saved = Prefs(tmp_path / "settings.json")
    assert saved.get("offset_ms", 0) == 1450
    assert saved.get("brightness_cap", 1.0) == 0.7
    assert saved.get("mode", "") == "bass_pump"
    assert saved.get("palette", "") == "ice"
    assert saved.get("beat_engine", "") == "predictive"


def test_calibration_mode_is_never_persisted(tmp_path: Path) -> None:
    from hue_party.prefs import Prefs

    prefs = Prefs(tmp_path / "settings.json")
    client = make_client(prefs=prefs)
    client.post("/api/mode", json={"mode": "calibration"})
    assert Prefs(tmp_path / "settings.json").get("mode", "unset") == "unset"


def test_restart_endpoint_requires_wiring_and_calls_restarter() -> None:
    assert make_client().post("/api/system/restart").status_code == 503
    calls = []
    client = make_client(restarter=lambda: calls.append(1))
    assert client.post("/api/system/restart").json() == {"ok": "restarting"}
    assert calls == [1]


def test_master_volume_endpoint_sets_all_speakers() -> None:
    client = make_client(speakers=make_speaker_control())
    assert client.post("/api/speakers/volume_all", json={"pct": 65}).json() == {"ok": "volume"}
    assert make_client().post("/api/speakers/volume_all", json={"pct": 65}).status_code == 503


def test_pwa_manifest_and_service_worker_are_served() -> None:
    client = make_client()
    manifest = client.get("/manifest.json")
    assert manifest.status_code == 200
    assert manifest.json()["name"] == "Hue Party"
    assert manifest.json()["display"] == "standalone"
    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert "javascript" in sw.headers["content-type"]
    assert sw.headers["cache-control"] == "no-cache"
    html = client.get("/").text
    assert 'rel="manifest"' in html
    assert "apple-touch-icon" in html


def test_recommended_endpoint() -> None:
    assert make_client().get("/api/music/recommended").status_code == 503

    class FakeMusicRec:
        async def recommended(self):
            return [{"video_id": "v1", "title": "T", "artist": "A", "thumb": None}]

    client = make_client(music=FakeMusicRec())
    assert client.get("/api/music/recommended").json()[0]["video_id"] == "v1"
