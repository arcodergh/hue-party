"""Keeps each module task alive: crash -> log -> backoff -> restart.

One module failing must never take down the show; the rest keep running.
"""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

log = logging.getLogger(__name__)

HEALTHY_RESET_S = 60.0


async def run_supervised(
    name: str,
    factory: Callable[[], Coroutine[Any, Any, None]],
    status: dict[str, str],
    *,
    base_backoff: float = 1.0,
    max_backoff: float = 30.0,
) -> None:
    backoff = base_backoff
    while True:
        status[name] = "running"
        started = time.monotonic()
        try:
            await factory()
            log.warning("module %s exited cleanly; restarting", name)
        except asyncio.CancelledError:
            status[name] = "stopped"
            raise
        except Exception:
            log.exception("module %s crashed; restarting in %.1fs", name, backoff)
        if time.monotonic() - started > HEALTHY_RESET_S:
            backoff = base_backoff
        status[name] = "restarting"
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, max_backoff)
