"""FastAPI app: REST + WebSocket for the phone UI (and Home Assistant later)."""

import hashlib
import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from hue_party.controller import ShowController
from hue_party.music import MusicError, video_id_to_url
from hue_party.player import PlayerError
from hue_party.speakers import SpeakerError

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_STATIC_REF = re.compile(r"/static/([\w.\-]+)")


def _versioned_html(name: str) -> str:
    """Serve the page with content-hashed static URLs (cache busting).

    A changed file gets a changed URL, so a browser can never pair a cached old
    script with a freshly deployed page. Hashing per request is fine at phone scale
    and means a deploy needs no server restart to bust caches.
    """

    def version(match: re.Match[str]) -> str:
        file = STATIC / match.group(1)
        if not file.is_file():
            return match.group(0)
        digest = hashlib.md5(file.read_bytes()).hexdigest()[:8]
        return f"{match.group(0)}?v={digest}"

    return _STATIC_REF.sub(version, (STATIC / name).read_text())


class ModeBody(BaseModel):
    mode: str


class PaletteBody(BaseModel):
    palette: str


class CalibrationBody(BaseModel):
    on: bool


class BeatEngineBody(BaseModel):
    engine: str


class OffsetBody(BaseModel):
    offset_ms: int = Field(ge=0, le=3000)


class BrightnessBody(BaseModel):
    cap: float = Field(ge=0.0, le=1.0)


class PanicBody(BaseModel):
    on: bool


class VoteBody(BaseModel):
    hue: float = Field(ge=0.0, le=1.0)


class MusicPlayBody(BaseModel):
    url: str | None = None
    video_id: str | None = None
    # Optional metadata (known when playing from search results) for the history list.
    title: str | None = None
    artist: str | None = None
    thumb: str | None = None


class SpeakerToggleBody(BaseModel):
    sink: str
    enabled: bool


class SpeakerVolumeBody(BaseModel):
    sink: str
    pct: int = Field(ge=0, le=100)


class MasterVolumeBody(BaseModel):
    pct: int = Field(ge=0, le=100)


def create_app(controller: ShowController, restarter: Callable[[], None] | None = None) -> FastAPI:
    app = FastAPI(title="hue-party")

    @app.middleware("http")
    async def revalidate_ui_files(request: Request, call_next: Any) -> Any:
        """Force etag revalidation on the UI files.

        Without an explicit Cache-Control, phone browsers heuristic-cache the static
        files and keep showing a pre-deploy UI; no-cache keeps 304s cheap but fresh.
        """
        response = await call_next(request)
        path = request.url.path
        if path in ("/", "/guest", "/manifest.json", "/sw.js") or path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/")
    async def index() -> HTMLResponse:
        return HTMLResponse(_versioned_html("index.html"))

    @app.get("/guest")
    async def guest() -> HTMLResponse:
        return HTMLResponse(_versioned_html("guest.html"))

    @app.get("/manifest.json")
    async def manifest() -> FileResponse:
        return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")

    @app.get("/sw.js")
    async def service_worker() -> FileResponse:
        # Served from the root so its scope covers the whole app.
        return FileResponse(STATIC / "sw.js", media_type="text/javascript")

    @app.get("/api/state")
    async def state() -> dict[str, object]:
        return controller.state()

    @app.post("/api/mode")
    async def set_mode(body: ModeBody) -> dict[str, object]:
        try:
            controller.set_mode(body.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return controller.state()

    @app.post("/api/calibration")
    async def set_calibration(body: CalibrationBody) -> dict[str, object]:
        await controller.set_calibration(body.on)
        return controller.state()

    @app.post("/api/palette")
    async def set_palette(body: PaletteBody) -> dict[str, object]:
        try:
            controller.set_palette(body.palette)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return controller.state()

    @app.post("/api/beat_engine")
    async def set_beat_engine(body: BeatEngineBody) -> dict[str, object]:
        if controller.analyzer is None:
            raise HTTPException(status_code=503, detail="Analyzer not available")
        try:
            controller.set_beat_engine(body.engine)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return controller.state()

    @app.post("/api/offset")
    async def set_offset(body: OffsetBody) -> dict[str, object]:
        controller.set_offset(body.offset_ms)
        return controller.state()

    @app.post("/api/brightness")
    async def set_brightness(body: BrightnessBody) -> dict[str, object]:
        controller.set_brightness(body.cap)
        return controller.state()

    @app.post("/api/panic")
    async def set_panic(body: PanicBody) -> dict[str, object]:
        controller.set_panic(body.on)
        return controller.state()

    @app.post("/api/system/restart")
    async def system_restart() -> dict[str, str]:
        if restarter is None:
            raise HTTPException(status_code=503, detail="Restart not available")
        restarter()
        return {"ok": "restarting"}

    @app.post("/api/party/stop")
    async def party_stop() -> dict[str, object]:
        await controller.stop_party()
        return controller.state()

    @app.post("/api/drop/start")
    async def drop_start() -> dict[str, object]:
        controller.drop_start()
        return controller.state()

    @app.post("/api/guest/vote")
    async def guest_vote(body: VoteBody) -> dict[str, str]:
        controller.vote(body.hue)
        return {"ok": "voted"}

    @app.get("/api/music/search")
    async def music_search(q: str) -> list[dict[str, object]]:
        if controller.music is None:
            raise HTTPException(status_code=503, detail="Music control not available")
        try:
            return await controller.music.search(q)
        except MusicError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/music/play")
    async def music_play(body: MusicPlayBody) -> dict[str, str]:
        if controller.music is None:
            raise HTTPException(status_code=503, detail="Music control not available")
        try:
            if body.video_id:
                url = video_id_to_url(body.video_id)
            elif body.url:
                url = body.url
            else:
                raise HTTPException(status_code=422, detail="Provide url or video_id")
            await controller.music.play(url)
        except MusicError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if controller.history is not None:
            try:
                title, artist = body.title, body.artist
                if not title:  # pasted URL: best-effort lookup, never blocks the play
                    meta = await controller.music.lookup_metadata(url)
                    title = meta.get("title")
                    artist = artist or meta.get("artist")
                controller.history.record(url, title=title, artist=artist, thumb=body.thumb)
            except Exception:
                log.warning("failed to record play history for %s", url, exc_info=True)
        return {"ok": "playing"}

    @app.get("/api/music/recommended")
    async def music_recommended() -> list[dict[str, object]]:
        if controller.music is None:
            raise HTTPException(status_code=503, detail="Music control not available")
        return await controller.music.recommended()

    @app.get("/api/music/history")
    async def music_history() -> dict[str, list[dict[str, object]]]:
        if controller.history is None:
            return {"tracks": [], "lists": []}
        return controller.history.entries()

    @app.get("/api/speakers")
    async def list_speakers() -> list[dict[str, object]]:
        if controller.speakers is None:
            raise HTTPException(status_code=503, detail="Speaker control not available")
        try:
            found = await controller.speakers.list_speakers()
        except SpeakerError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return [
            {
                "sink": s.sink_name,
                "name": s.description,
                "enabled": s.enabled,
                "volume_pct": s.volume_pct,
            }
            for s in found
        ]

    @app.post("/api/speakers/toggle")
    async def toggle_speaker(body: SpeakerToggleBody) -> dict[str, str]:
        if controller.speakers is None:
            raise HTTPException(status_code=503, detail="Speaker control not available")
        try:
            if body.enabled:
                await controller.speakers.enable(body.sink)
            else:
                await controller.speakers.disable(body.sink)
        except SpeakerError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": "toggled"}

    @app.post("/api/speakers/volume_all")
    async def master_volume(body: MasterVolumeBody) -> dict[str, str]:
        if controller.speakers is None:
            raise HTTPException(status_code=503, detail="Speaker control not available")
        try:
            await controller.speakers.set_all_volumes(body.pct)
        except SpeakerError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": "volume"}

    @app.post("/api/speakers/rescan")
    async def speakers_rescan() -> dict[str, str]:
        if controller.speakers is None:
            raise HTTPException(status_code=503, detail="Speaker control not available")
        try:
            await controller.speakers.rescan()
        except SpeakerError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": "rescanned"}

    @app.post("/api/speakers/volume")
    async def speaker_volume(body: SpeakerVolumeBody) -> dict[str, str]:
        if controller.speakers is None:
            raise HTTPException(status_code=503, detail="Speaker control not available")
        try:
            await controller.speakers.set_volume(body.sink, body.pct)
        except SpeakerError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": "volume"}

    @app.get("/api/art")
    async def get_art() -> Response:
        if controller.player is None:
            raise HTTPException(status_code=503, detail="Player control not available")
        url = await controller.player.art_url()
        if not url or not url.startswith("file://"):
            raise HTTPException(status_code=404, detail="No album art available")
        path = Path(url.removeprefix("file://"))
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Album art file not found")
        data = path.read_bytes()
        content_type = "image/png" if data[:8] == PNG_MAGIC else "image/jpeg"
        headers = {"Cache-Control": "no-store"}
        return Response(content=data, media_type=content_type, headers=headers)

    @app.post("/api/player/{action}")
    async def player_action(action: str) -> dict[str, str]:
        if controller.player is None:
            raise HTTPException(status_code=503, detail="Player control not available")
        actions = {
            "play_pause": controller.player.play_pause,
            "next": controller.player.next_track,
            "previous": controller.player.previous_track,
        }
        if action not in actions:
            raise HTTPException(status_code=404, detail=f"Unknown action '{action}'")
        try:
            await actions[action]()
        except PlayerError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": action}

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        try:
            await socket.send_json(controller.state())
            while True:
                await controller.wait_change(timeout=1.0)
                await socket.send_json(controller.state())
        except WebSocketDisconnect:
            return

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app
