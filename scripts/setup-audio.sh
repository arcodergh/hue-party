#!/usr/bin/env bash
# One-time (per boot) audio plumbing: Chrome -> music_bus -> [analyzer, Sonos AirPlay].
# Idempotent: safe to re-run. PipeWire modules loaded via pactl do not survive reboot;
# re-run this script (or see README for the pipewire.conf.d permanent setup).
set -euo pipefail

echo "== 1/4 virtual sink 'music_bus'"
if pactl list short sinks | cut -f2 | grep -qx music_bus; then
  echo "   already present"
else
  pactl load-module module-null-sink media.class=Audio/Sink sink_name=music_bus channel_map=stereo
  echo "   created"
fi

echo "== 2/4 avahi (AirPlay discovery)"
if systemctl is-active --quiet avahi-daemon; then
  echo "   running"
else
  echo "   WARNING: avahi-daemon not running -> sudo systemctl enable --now avahi-daemon"
fi

echo "== 3/4 AirPlay (RAOP) discovery module"
if pactl list short modules | grep -q module-raop-discover; then
  echo "   already loaded"
else
  pactl load-module module-raop-discover
  echo "   loaded; waiting for Sonos to appear..."
  sleep 4
fi

echo "== 4/4 loopback music_bus -> Sonos"
SONOS_SINK=$(pactl list short sinks | cut -f2 | grep -i raop | head -n1 || true)
if [ -z "${SONOS_SINK}" ]; then
  echo "   No AirPlay sink found. Check: same LAN, avahi running, firewall allows"
  echo "   mDNS (UDP 5353) and RTP (UDP 6001-6002). See README 'Sonos troubleshooting'."
  exit 1
fi
if pactl list short modules | grep module-loopback | grep -q music_bus; then
  echo "   already linked"
else
  pactl load-module module-loopback source=music_bus.monitor sink="${SONOS_SINK}" latency_msec=200
  echo "   linked music_bus -> ${SONOS_SINK}"
fi

echo
echo "Done. Final manual step: in pavucontrol (Playback tab) or GNOME sound settings,"
echo "move Chrome's output to 'music_bus'. PipeWire remembers this for Chrome."
