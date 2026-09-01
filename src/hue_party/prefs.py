"""Host-tuned settings that survive restarts (delay, brightness, mode, ...).

``config/application.yaml`` stays the fresh-install baseline; this small JSON
file holds what the host actually dialed in from the phone on THIS machine —
most importantly the calibrated light delay, which is painful to lose on every
service restart.
"""

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_PREFS_PATH = Path("~/.config/hue-party/settings.json")


class Prefs:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, Any] = {}
        try:
            if path.exists():
                loaded = json.loads(path.read_text())
                if isinstance(loaded, dict):
                    self._data = loaded
        except (OSError, ValueError):
            log.warning("unreadable prefs at %s; starting fresh", path, exc_info=True)

    def get(self, key: str, default: Any) -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data))
        except OSError:
            log.warning("could not persist prefs to %s", self._path, exc_info=True)
