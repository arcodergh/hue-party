# hue-party — Design Spec

**Date:** 2026-08-29
**Status:** Approved design, pre-implementation

## 1. Purpose

A self-hosted "Hue Sync, but mine" party system. Music plays from YouTube Music
in Chrome on an Ubuntu server, comes out of Sonos speakers via AirPlay, and
Philips Hue lights react to the music in real time. The host controls the show
from a phone; guests interact from theirs. No reverse engineering — everything
rides on official/local APIs (Hue Entertainment API v2, PipeWire, MPRIS, Sonos
AirPlay).

## 2. Hardware & environment

- Ubuntu server (modern release, PipeWire audio stack), Chrome logged into
  YouTube Music (Premium).
- Philips Hue square (v2) Bridge.
- Fast lights (entertainment area): 3 × Hue color bulbs + 1 × Hue Play.
- Slow lights: several Hue white bulbs (cannot join entertainment streaming).
- Sonos speakers with AirPlay 2 support, same LAN.
- Phones on the same LAN (host + guests), no app installs.

### Hue Entertainment API constraints (design inputs)

- One active entertainment area per bridge, max 10 lights.
- Client sends 50–60 frames/sec over DTLS/UDP (port 2100,
  TLS_PSK_WITH_AES_128_GCM_SHA256); effective Zigbee output ≈ 25 Hz per light.
- v2 frames address *channels* (a light's position-bearing color point), with
  x/y/z positions configured in the Hue app's entertainment area.
- Bridge auto-stops the stream after ~10 s without frames; client must keep
  alive and re-handshake on drop.
- Pairing: link button → `POST /api` with `generateclientkey: true` → store
  `username` (application key) + `clientkey` (DTLS PSK).

## 3. Architecture

One Python service, five modules with clean interfaces:

```
Chrome (YouTube Music)
   │ plays into
   ▼
PipeWire "music_bus" (virtual null sink)
   ├─► [1] Audio Analyzer ─AudioFrame─► [2] Effect Engine ─LightFrame─► [3] Light Streamer ─► Hue Bridge ─► lights
   └─► AirPlay (RAOP) ─► Sonos                  ▲              (delay ring buffer in [3])
                                                │
                   [4] Web UI + API (FastAPI) ──┘◄── host phone + guest phones
                   [5] Player Control (MPRIS/playerctl) ─► Chrome play/pause/skip
```

Each module runs as its own async task; modules communicate via in-process
queues/pub-sub with two typed messages:

- **`AudioFrame`** (~60/sec): beat flag, onset flag, low/mid/high band energies
  (smoothed), overall volume, rolling tempo estimate, timestamp.
- **`LightFrame`** (50/sec): color + brightness per entertainment channel, plus
  optional coarse commands for white bulbs; timestamp.

### Module responsibilities

1. **Audio Analyzer** — captures `music_bus.monitor` (stereo float32,
   ~44.1 kHz, ~23 ms chunks) via `sounddevice`; FFT + onset/beat/tempo via
   `aubio` (the maintained `aubio-ledfx` fork). Recipe cribbed from LedFx's
   `ledfx/effects/audio.py` (mel bands, `volume_beat_now`-style bass-vs-rolling-
   average beat, `aubio.tempo`/`onset`).
2. **Effect Engine** — pluggable effect-mode classes, pure functions of
   `AudioFrame` + mode state → `LightFrame`. Handles palettes, triggered
   moments (drop), guest crowd-color influence, brightness cap, panic mode.
   All business logic lives here; fully unit-testable with synthetic frames.
3. **Light Streamer** — delay ring buffer (the latency offset), then:
   - Fast path: `hue-entertainment` (Music Assistant's pure-Python DTLS lib,
     PyPI) streaming at 50 fps; keepalive; auto re-handshake on stream drop.
   - Slow path: Hue REST (via `aiohue`) for white bulbs, ≤ ~2 commands/sec.
4. **Web UI + API** — FastAPI; one WebSocket for live state + guest events;
   REST endpoints mirroring every action (Home Assistant hook for later).
5. **Player Control** — MPRIS via `playerctl` wrapper: play/pause/next/prev,
   current track metadata (shown in UI; new-track events available to effects).

## 4. Audio pipeline & latency

**Plumbing** (one-time `scripts/setup-audio.sh`, idempotent; the app assumes it
ran and preflight-checks the result):

- Create persistent PipeWire null sink `music_bus`; route Chrome's output to it.
- Load `module-raop-discover` with `raop.encryption.type = auth_setup` (required
  for AirPlay-2-era Sonos); avahi must be running; requires UDP 6001–6002 +
  control ports open (script checks and reports).
- Link `music_bus.monitor` → Sonos RAOP sink; `raop.latency.ms ≈ 1000` for
  stability.

**Fallback (designed-in, build only if needed):** serve `music_bus.monitor` as a
local HTTP/Icecast stream (ffmpeg) and have Sonos pull it via `SoCo`
(`play_uri`). Larger (~3–6 s) but constant delay; absorbed by the same offset
knob. Works on all Sonos models.

**Latency compensation:** analyzer hears audio ~20 ms after Chrome plays it;
Sonos plays ~0.3–1.5 s later (AirPlay) — so light output is buffered and
released `offset` ms later. `offset` is a live slider (0–3000 ms) in the web
UI, calibrated by eye once per session. A **calibration mode** flashes all
lights white exactly on detected beats to make tuning trivial.

## 5. Effects & light behavior

**Launch modes** (each a small class; mode × palette are independent):

- **Beat Flash** — pulse on beat, palette color rotation, bass rides brightness.
- **Color Wave** — hue gradient travels across the room using channel x/y
  positions; speed follows tempo.
- **Bass Pump** — color from mid/high bands, brightness slammed by bass; the
  Hue Play is the "subwoofer" light.
- **Chill Drift** — slow color morph, gentle volume swells.

**Palettes:** named sets (Fiesta, Neon, Sunset, Ice, …) selectable per mode.

**Choreographed moments:** **Strobe Drop** — hold-to-build (dim + tighten to
white), release = strobe burst, auto-return to previous mode. Implemented as a
temporary mode override; more moments can be added the same way.

**White bulbs:** ambient layer only — brightness dips/rises on phrase-level
changes and drops, ≤ ~2 REST commands/sec.

**Guest interaction (v1):** guests open `/guest` and tap a color pad; votes
bend the active palette toward the crowd's average color over ~10 s; a crowd-
color indicator shows their influence. Nothing a guest does can break the show.

**Safety rails:** global brightness cap slider; strobe rate capped at ~8 Hz
(photosensitivity courtesy); **panic button** = warm white, full brightness,
sync off.

Out of scope for v1 (architecture allows later): freeze-dance/party games,
Home Assistant integration, >10 lights, gradient strips, multi-room audio sync.

## 6. Web UI & API

Mobile-first single page, plain HTML/JS served by FastAPI (no build toolchain).

- **`/` host view:** start/stop show, mode picker, palette picker, latency
  slider + calibration toggle, brightness cap, panic, drop button,
  play/pause/skip + current track, module status badges, guest QR code.
- **`/guest` view:** color pad + crowd-color indicator only.
- **Transport:** one WebSocket (state broadcast + guest events); every host
  action also exists as REST (`POST /api/mode`, `POST /api/drop`,
  `POST /api/offset`, `POST /api/player/next`, `GET /api/state`, …).

## 7. Configuration & secrets

- `config/application.yaml` (versioned): bridge IP, entertainment area id,
  ports, default mode/palette/offset, white-bulb ids, rate limits.
- `.env` (gitignored; `.env.example` committed): `HUE_APP_KEY`,
  `HUE_CLIENT_KEY` — obtained once via a guided `hue-party pair` CLI command
  (press link button, keys stored).

## 8. Error handling

- Per-module supervision: a crashing task restarts with backoff and surfaces a
  status badge; the show never dies wholesale. Audio, lights, and player
  control fail independently.
- Hue stream drop → automatic re-handshake and resume.
- Startup preflight with actionable messages: `music_bus` exists? bridge
  reachable? entertainment area configured & inactive? keys present? Sonos
  sink present (warn only)?
- All external-edge errors logged with context; no silent swallowing.

## 9. Testing

- **Unit (deterministic, fast):** effect modes (synthetic `AudioFrame`s →
  asserted `LightFrame`s), delay ring buffer timing logic, crowd-color
  averaging, palette math, config parsing. This covers most custom logic.
- **Edges wrapped thin:** DTLS streaming, audio capture, MPRIS behind small
  interfaces with fakes for tests.
- **`--simulate` mode:** renders light channels as colored blocks in the
  terminal — develop effects without hardware.
- **Manual hardware checklist:** pairing, static color via stream, beat sync on
  real lights, Sonos latency calibration, white-bulb cues, guest pad from a
  second phone.

## 10. Build order (each step independently verifiable)

1. Project scaffold, config, pairing CLI + static color via entertainment stream.
2. Audio analyzer printing beats/energies to console.
3. Effect engine + terminal simulator + Beat Flash.
4. Delay buffer + real-light streaming (Beat Flash on hardware).
5. Web UI (host view) + WebSocket state.
6. Player control (playerctl).
7. Remaining modes + palettes + drop moment.
8. White-bulb slow path.
9. Guest view + crowd color.
10. `setup-audio.sh` + Sonos AirPlay leg + calibration mode.

## 11. Key dependencies (to be pinned)

`hue-entertainment` (Music Assistant), `aiohue`, `aubio-ledfx`, `sounddevice`,
`fastapi`, `uvicorn`, `pydantic`, `pyyaml`; system: `playerctl`, PipeWire
(+ `libspa-0.2-modules` RAOP), `avahi-daemon`. Fallback only: `SoCo`, `ffmpeg`.

## 12. Reference material

- LedFx source (analysis recipe): https://github.com/LedFx/LedFx
- Music Assistant hue-entertainment: https://github.com/music-assistant/hue-entertainment
- Hue Entertainment protocol walkthrough: https://iotech.blog/posts/philips-hue-entertainment-api/
- OpenHue CLIP v2 spec: https://github.com/openhue/openhue-api
- PipeWire RAOP → Sonos field guide: https://technologiehub.at/project-posts/systemsound-over-sonos-linux-ubuntu/
- Latency-offset precedent (0–3000 ms knob): https://www.music-assistant.io/plugins/hue-entertainment/
