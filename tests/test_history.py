import json
from pathlib import Path

from hue_party.history import PlayHistory, classify


def test_classify_watch_urls_as_tracks() -> None:
    assert classify("https://music.youtube.com/watch?v=abc123") == ("tracks", "abc123")
    assert classify("https://youtu.be/xyz789") == ("tracks", "xyz789")


def test_classify_list_urls_as_lists_even_with_video() -> None:
    assert classify("https://music.youtube.com/playlist?list=PL42") == ("lists", "PL42")
    assert classify("https://www.youtube.com/watch?v=abc&list=PL42") == ("lists", "PL42")


def test_classify_rejects_unrecognized_urls() -> None:
    assert classify("https://music.youtube.com/") is None


def make(tmp_path: Path) -> PlayHistory:
    return PlayHistory(tmp_path / "history.json", limit=3, clock=lambda: 1000.0)


def test_record_keeps_newest_first_dedupes_and_caps(tmp_path: Path) -> None:
    history = make(tmp_path)
    for vid in ("a1234", "b1234", "c1234", "a1234", "d1234"):
        history.record(f"https://music.youtube.com/watch?v={vid}", title=vid.upper())
    tracks = history.entries()["tracks"]
    assert [t["id"] for t in tracks] == ["d1234", "a1234", "c1234"]  # limit=3, deduped
    assert tracks[1]["title"] == "A1234"


def test_tracks_and_lists_are_separate_buckets(tmp_path: Path) -> None:
    history = make(tmp_path)
    history.record("https://music.youtube.com/watch?v=abc12")
    history.record("https://music.youtube.com/playlist?list=PL42", title="Party Mix")
    entries = history.entries()
    assert [t["id"] for t in entries["tracks"]] == ["abc12"]
    assert [x["id"] for x in entries["lists"]] == ["PL42"]


def test_history_persists_across_instances(tmp_path: Path) -> None:
    make(tmp_path).record("https://music.youtube.com/watch?v=abc12", title="Song")
    reloaded = PlayHistory(tmp_path / "history.json", limit=3)
    assert reloaded.entries()["tracks"][0]["title"] == "Song"


def test_corrupt_history_file_starts_fresh(tmp_path: Path) -> None:
    (tmp_path / "history.json").write_text("{not json")
    history = make(tmp_path)
    assert history.entries() == {"tracks": [], "lists": []}
    history.record("https://music.youtube.com/watch?v=abc12")
    assert json.loads((tmp_path / "history.json").read_text())["tracks"][0]["id"] == "abc12"


def test_unclassifiable_urls_are_ignored(tmp_path: Path) -> None:
    history = make(tmp_path)
    history.record("https://music.youtube.com/")
    assert history.entries() == {"tracks": [], "lists": []}
