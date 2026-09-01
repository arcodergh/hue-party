"""Recently played YouTube tracks and lists, persisted across restarts."""

import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

log = logging.getLogger(__name__)

DEFAULT_HISTORY_PATH = Path("~/.config/hue-party/history.json")
DEFAULT_LIMIT = 10


def classify(url: str) -> tuple[str, str] | None:
    """Return ("tracks"|"lists", id) for a YouTube URL, or None if it is neither.

    A ``list=`` parameter wins over ``v=``: opening a watch URL that carries a list
    starts playlist playback, so it belongs in the lists bucket.
    """
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    list_ids = query.get("list") or []
    if list_ids and list_ids[0]:
        return ("lists", list_ids[0])
    video_ids = query.get("v") or []
    video_id = video_ids[0] if video_ids else ""
    if parsed.hostname == "youtu.be":
        video_id = parsed.path.strip("/") or video_id
    if video_id:
        return ("tracks", video_id)
    return None


class PlayHistory:
    """Newest-first, deduped, capped play history in a small JSON file."""

    def __init__(
        self,
        path: Path,
        limit: int = DEFAULT_LIMIT,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._limit = limit
        self._clock = clock
        self._data: dict[str, list[dict[str, object]]] = {"tracks": [], "lists": []}
        try:
            if path.exists():
                loaded = json.loads(path.read_text())
                self._data = {
                    "tracks": list(loaded.get("tracks") or []),
                    "lists": list(loaded.get("lists") or []),
                }
        except (OSError, ValueError):
            log.warning("unreadable play history at %s; starting fresh", path, exc_info=True)

    def record(
        self,
        url: str,
        *,
        title: str | None = None,
        artist: str | None = None,
        thumb: str | None = None,
    ) -> None:
        classified = classify(url)
        if classified is None:
            log.debug("not recording unrecognized play URL %s", url)
            return
        kind, item_id = classified
        bucket = [e for e in self._data[kind] if e.get("id") != item_id]
        bucket.insert(
            0,
            {
                "id": item_id,
                "url": url,
                "title": title,
                "artist": artist,
                "thumb": thumb,
                "played_at": self._clock(),
            },
        )
        self._data[kind] = bucket[: self._limit]
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data))
        except OSError:
            log.warning("could not persist play history to %s", self._path, exc_info=True)

    def entries(self) -> dict[str, list[dict[str, object]]]:
        return {"tracks": list(self._data["tracks"]), "lists": list(self._data["lists"])}
