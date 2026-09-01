#!/usr/bin/env bash
# Install hue-party as a systemd *user* service: starts with your session,
# restarts on crash, logs to journald. Run as the user who owns the checkout.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR"
cp "$REPO_DIR/deploy/hue-party.service" "$UNIT_DIR/hue-party.service"
systemctl --user daemon-reload
systemctl --user enable --now hue-party
systemctl --user status hue-party --no-pager || true

echo
echo "Installed. Useful commands:"
echo "  systemctl --user status hue-party     # health"
echo "  journalctl --user -u hue-party -f     # live logs"
echo "  systemctl --user restart hue-party    # restart"
echo "  systemctl --user disable --now hue-party  # remove from startup"
echo
echo "To keep it running when you're logged OUT (headless boot), run once:"
echo "  sudo loginctl enable-linger $USER"
