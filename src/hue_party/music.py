"""Pick music from the phone: YouTube Music search + app-managed Chrome playback.

Search uses ytmusicapi (unofficial, keyless). Playback goes through a Chrome
instance the app OWNS: launched on demand with a dedicated profile and the
localhost DevTools port, so the app can open each requested song and close the
previous music tab — always exactly one music tab, and closing Chrome by hand
just means the next play relaunches it.

Chrome (136+) only honors --remote-debugging-port with a non-default
--user-data-dir, hence the dedicated profile; log into YouTube Music once in
that profile and it persists.
"""

import asyncio
import contextlib
import logging
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp
from ytmusicapi import YTMusic

from hue_party.history import classify

log = logging.getLogger(__name__)

Runner = Callable[..., Awaitable[tuple[int, str, str]]]
Spawner = Callable[..., Awaitable[None]]

ALLOWED_HOSTS = {"music.youtube.com", "www.youtube.com", "youtube.com", "youtu.be"}

# Curated picks that the beat engines lock onto beautifully. Stored as queries and
# resolved through YouTube Music search (never hardcoded video ids, which rot).
RECOMMENDED_QUERIES = (
    "Daft Punk Giorgio by Moroder",
    "Daft Punk One More Time",
    "Michael Jackson Billie Jean",
    "Michael Jackson Beat It",
    "Avicii Levels",
    "Avicii Wake Me Up",
    "Linkin Park Bleed It Out",
    "Linkin Park Numb",
    "Daft Punk Harder Better Faster Stronger",
    "Queen Another One Bites the Dust",
    "The Chemical Brothers Galvanize",
    "The Prodigy Breathe",
    "Justice D.A.N.C.E.",
    "Eurythmics Sweet Dreams (Are Made of This)",
    "Blur Song 2",
)
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{5,20}$")
BROWSER_START_TIMEOUT_S = 20.0


class MusicError(RuntimeError):
    pass


async def _exec(*args: str) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    out, err = await proc.communicate()
    return proc.returncode or 0, out.decode(), err.decode()


async def _spawn_detached(*args: str) -> None:
    """Start a long-lived process (Chrome) without waiting for it to exit."""
    await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise MusicError("Only https:// YouTube links are supported")
    if parsed.hostname not in ALLOWED_HOSTS:
        raise MusicError(f"Not a YouTube link: {parsed.hostname}")
    return url


def video_id_to_url(video_id: str) -> str:
    if not VIDEO_ID_RE.match(video_id):
        raise MusicError("Invalid video id")
    return f"https://music.youtube.com/watch?v={video_id}"


def _is_music_tab(tab: dict[str, Any]) -> bool:
    if tab.get("type") != "page":
        return False
    host = urlparse(tab.get("url", "")).hostname
    return host in ALLOWED_HOSTS


class MusicControl:
    def __init__(
        self,
        browser: str = "google-chrome",
        debug_port: int = 9222,
        profile_dir: str = "~/.config/hue-party/chrome-profile",
        runner: Runner = _exec,
        spawner: Spawner = _spawn_detached,
        search_client: Any | None = None,  # Any: ytmusicapi ships no type stubs
    ) -> None:
        self._browser = browser
        self._port = debug_port
        self._profile_dir = Path(profile_dir).expanduser()
        self._run = runner
        self._spawn = spawner
        self._client = search_client
        self._recommended: list[dict[str, object]] | None = None

    def _ytmusic(self) -> Any:
        if self._client is None:
            self._client = YTMusic()
        return self._client

    async def search(self, query: str, limit: int = 8) -> list[dict[str, object]]:
        """Search YouTube Music songs; sync ytmusicapi call runs in a thread."""

        def _do_search() -> list[dict[str, Any]]:
            found: list[dict[str, Any]] = self._ytmusic().search(query, filter="songs", limit=limit)
            return found

        try:
            results = await asyncio.to_thread(_do_search)
        except Exception as exc:
            raise MusicError(f"YouTube Music search failed: {exc}") from exc
        tracks: list[dict[str, object]] = []
        for item in results[:limit]:
            video_id = item.get("videoId")
            if not video_id:
                continue
            thumbs = item.get("thumbnails") or []
            tracks.append(
                {
                    "video_id": video_id,
                    "title": item.get("title", "?"),
                    "artist": ", ".join(a.get("name", "") for a in item.get("artists") or []),
                    "duration": item.get("duration", ""),
                    "thumb": thumbs[0]["url"] if thumbs else None,
                }
            )
        return tracks

    async def recommended(self) -> list[dict[str, object]]:
        """The curated picks, resolved via search once and cached for the session."""
        if self._recommended is not None:
            return self._recommended
        picks: list[dict[str, object]] = []
        for query in RECOMMENDED_QUERIES:
            try:
                results = await self.search(query, limit=1)
            except MusicError:
                log.warning("could not resolve recommended pick %r", query, exc_info=True)
                continue
            if results:
                picks.append(results[0])
        if picks:  # resolve again next time if everything failed (e.g. offline)
            self._recommended = picks
        return picks

    async def lookup_metadata(self, url: str) -> dict[str, str]:
        """Best-effort title/artist for a pasted URL; empty dict when unknown."""

        def _do_lookup() -> dict[str, str]:
            classified = classify(url)
            if classified is None:
                return {}
            kind, item_id = classified
            client = self._ytmusic()
            if kind == "lists":
                title = (client.get_playlist(item_id, limit=1) or {}).get("title")
                return {"title": title} if title else {}
            details = (client.get_song(item_id) or {}).get("videoDetails") or {}
            found: dict[str, str] = {}
            if details.get("title"):
                found["title"] = details["title"]
            if details.get("author"):
                found["artist"] = details["author"]
            return found

        try:
            return await asyncio.to_thread(_do_lookup)
        except Exception:
            log.info("metadata lookup failed for %s", url, exc_info=True)
            return {}

    # --- Chrome DevTools (localhost HTTP) -----------------------------------

    async def _cdp(self, method: str, path: str) -> tuple[int, Any]:
        url = f"http://127.0.0.1:{self._port}{path}"
        timeout = aiohttp.ClientTimeout(total=3)
        async with aiohttp.ClientSession(timeout=timeout) as session:  # noqa: SIM117
            async with session.request(method, url) as resp:
                body: Any = None
                with contextlib.suppress(Exception):  # /json/close returns plain text
                    body = await resp.json(content_type=None)
                return resp.status, body

    async def _browser_alive(self) -> bool:
        try:
            status, _ = await self._cdp("GET", "/json/version")
        except aiohttp.ClientError:
            return False
        except OSError:
            return False
        return status == 200

    async def _ensure_browser(self) -> None:
        if await self._browser_alive():
            return
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        log.info("launching %s with party profile %s", self._browser, self._profile_dir)
        await self._spawn(
            self._browser,
            f"--remote-debugging-port={self._port}",
            f"--user-data-dir={self._profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            # This Chrome exists only to play party music; without the flag a fresh
            # launch blocks YT Music autoplay until a human clicks on vision's desktop.
            "--autoplay-policy=no-user-gesture-required",
            "https://music.youtube.com",
        )
        deadline = asyncio.get_running_loop().time() + BROWSER_START_TIMEOUT_S
        while asyncio.get_running_loop().time() < deadline:
            if await self._browser_alive():
                return
            await asyncio.sleep(0.5)
        raise MusicError(
            f"Chrome did not come up on the debug port within {BROWSER_START_TIMEOUT_S:.0f}s "
            f"(is DISPLAY set and '{self._browser}' installed?)"
        )

    async def play(self, url: str) -> None:
        """Open the URL in the app's Chrome, replacing the previous music tab."""
        url = validate_url(url)
        await self._ensure_browser()

        rc, _, err = await self._run("playerctl", "pause")
        if rc != 0:  # best-effort: nothing playing yet is fine
            log.debug("playerctl pause before open failed (ignored): %s", err.strip())

        status, before = await self._cdp("GET", "/json/list")
        old_ids = [t["id"] for t in before or [] if _is_music_tab(t)] if status == 200 else []

        status, new_tab = await self._cdp("PUT", f"/json/new?{quote(url, safe=':/?&=')}")
        if status == 405:  # older Chrome wants GET here
            status, new_tab = await self._cdp("GET", f"/json/new?{quote(url, safe=':/?&=')}")
        if status != 200 or not isinstance(new_tab, dict):
            raise MusicError(f"Chrome refused to open the tab (HTTP {status})")

        for old_id in old_ids:
            if old_id != new_tab.get("id"):
                with contextlib.suppress(aiohttp.ClientError, OSError):
                    await self._cdp("GET", f"/json/close/{old_id}")
