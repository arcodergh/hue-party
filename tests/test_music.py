from typing import Any

import pytest

from hue_party.music import MusicControl, MusicError, validate_url, video_id_to_url


def fake_runner(responses: dict[tuple[str, ...], tuple[int, str, str]]):
    calls: list[tuple[str, ...]] = []

    async def run(*args: str) -> tuple[int, str, str]:
        calls.append(args)
        return responses.get(args, (0, "", ""))

    return run, calls


def test_validate_url_accepts_youtube_hosts() -> None:
    for url in (
        "https://music.youtube.com/watch?v=abc123",
        "https://music.youtube.com/playlist?list=PLx",
        "https://www.youtube.com/watch?v=abc123",
        "https://youtu.be/abc123",
    ):
        assert validate_url(url) == url


def test_validate_url_rejects_non_youtube_and_non_https() -> None:
    with pytest.raises(MusicError, match="Not a YouTube link"):
        validate_url("https://evil.example.com/watch?v=abc")
    with pytest.raises(MusicError, match="https"):
        validate_url("http://music.youtube.com/watch?v=abc")
    with pytest.raises(MusicError, match="https"):
        validate_url("file:///etc/passwd")


def test_video_id_to_url_builds_watch_url_and_rejects_junk() -> None:
    assert video_id_to_url("dQw4w9WgXcQ") == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    with pytest.raises(MusicError):
        video_id_to_url("not a video id; rm -rf /")


class FakeCdp:
    """Stands in for MusicControl._cdp: scripted responses + a call log."""

    def __init__(self, alive: bool = True, alive_after_spawn: bool = True) -> None:
        self.alive = alive
        self.alive_after_spawn = alive_after_spawn
        self.calls: list[tuple[str, str]] = []
        self.tabs: list[dict[str, Any]] = [
            {"id": "old-music", "type": "page", "url": "https://music.youtube.com/watch?v=prev"},
            {"id": "other", "type": "page", "url": "https://example.com/"},
        ]

    async def __call__(self, method: str, path: str) -> tuple[int, Any]:
        self.calls.append((method, path))
        if path == "/json/version":
            return (200, {"Browser": "Chrome"}) if self.alive else (500, None)
        if path == "/json/list":
            return 200, list(self.tabs)
        if path.startswith("/json/new"):
            return 200, {"id": "new-tab"}
        if path.startswith("/json/close/"):
            return 200, None
        raise AssertionError(f"unexpected CDP call {method} {path}")


def make_control(cdp: FakeCdp) -> tuple[MusicControl, list[tuple[str, ...]], list[tuple[str, ...]]]:
    run_calls: list[tuple[str, ...]] = []
    spawn_calls: list[tuple[str, ...]] = []

    async def run(*args: str) -> tuple[int, str, str]:
        run_calls.append(args)
        return (0, "", "")

    async def spawn(*args: str) -> None:
        spawn_calls.append(args)
        cdp.alive = cdp.alive_after_spawn

    control = MusicControl(browser="google-chrome", runner=run, spawner=spawn)
    control._cdp = cdp  # type: ignore[method-assign]
    return control, run_calls, spawn_calls


async def test_play_reuses_running_browser_and_replaces_music_tab() -> None:
    cdp = FakeCdp(alive=True)
    control, run_calls, spawn_calls = make_control(cdp)
    await control.play("https://music.youtube.com/watch?v=abc123")

    assert spawn_calls == []  # browser already up: no launch
    assert ("playerctl", "pause") in run_calls
    new_calls = [c for c in cdp.calls if c[1].startswith("/json/new")]
    assert len(new_calls) == 1 and "music.youtube.com/watch?v=abc123" in new_calls[0][1]
    assert ("GET", "/json/close/old-music") in cdp.calls  # previous music tab closed
    assert not any(p == "/json/close/other" for _, p in cdp.calls)  # non-music tab untouched


async def test_play_launches_browser_with_dedicated_profile_when_down() -> None:
    cdp = FakeCdp(alive=False, alive_after_spawn=True)
    control, _, spawn_calls = make_control(cdp)
    await control.play("https://youtu.be/abc123")

    assert len(spawn_calls) == 1
    argv = spawn_calls[0]
    assert argv[0] == "google-chrome"
    assert "--remote-debugging-port=9222" in argv
    assert any(a.startswith("--user-data-dir=") for a in argv)
    # A freshly launched Chrome blocks YT Music autoplay without this, which cascades:
    # no playback -> no MPRIS -> watchdog sees "no music" -> light stream never starts.
    assert "--autoplay-policy=no-user-gesture-required" in argv


async def test_play_fails_actionably_when_browser_never_comes_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("hue_party.music.BROWSER_START_TIMEOUT_S", 0.05)
    cdp = FakeCdp(alive=False, alive_after_spawn=False)
    control, _, _ = make_control(cdp)
    with pytest.raises(MusicError, match="debug port"):
        await control.play("https://youtu.be/abc123")


class FakeYTMusic:
    def search(self, query: str, filter: str, limit: int) -> list[dict[str, object]]:
        return [
            {
                "videoId": "vid1",
                "title": "One More Time",
                "artists": [{"name": "Daft Punk"}],
                "duration": "5:20",
                "thumbnails": [{"url": "https://img/1.jpg"}],
            },
            {"title": "no-videoId entries are skipped"},
        ]


async def test_search_normalizes_results_and_skips_unplayable() -> None:
    run, _ = fake_runner({})
    control = MusicControl(runner=run, search_client=FakeYTMusic())
    tracks = await control.search("daft punk")
    assert tracks == [
        {
            "video_id": "vid1",
            "title": "One More Time",
            "artist": "Daft Punk",
            "duration": "5:20",
            "thumb": "https://img/1.jpg",
        }
    ]


class FakeYtMusic:
    """Scripted ytmusicapi stand-in for search/recommended resolution."""

    def __init__(self) -> None:
        self.searches: list[str] = []

    def search(self, query: str, filter: str, limit: int):  # noqa: A002
        self.searches.append(query)
        slug = query.split()[0].lower()
        return [
            {
                "videoId": f"vid_{slug}",
                "title": f"Title {slug}",
                "artists": [{"name": "Artist"}],
                "duration": "3:33",
                "thumbnails": [{"url": f"http://t/{slug}.jpg"}],
            }
        ]


async def test_recommended_resolves_curated_queries_and_caches() -> None:
    yt = FakeYtMusic()
    control = MusicControl(search_client=yt)
    picks = await control.recommended()
    assert len(picks) >= 5  # the curated list resolved
    assert all(p["video_id"] and p["title"] for p in picks)
    first_search_count = len(yt.searches)
    await control.recommended()  # second call must come from the cache
    assert len(yt.searches) == first_search_count


async def test_recommended_skips_entries_that_fail_to_resolve() -> None:
    class FlakyYt(FakeYtMusic):
        def search(self, query: str, filter: str, limit: int):  # noqa: A002
            if "Avicii" in query:
                raise RuntimeError("quota")
            return super().search(query, filter, limit)

    picks = await MusicControl(search_client=FlakyYt()).recommended()
    assert picks  # one bad entry must not empty the list
    assert not any("avicii" in (p["video_id"] or "") for p in picks)
