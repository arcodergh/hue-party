import asyncio

import pytest

from hue_party.supervisor import run_supervised


async def test_restarts_after_crash_and_tracks_status() -> None:
    runs = 0
    status: dict[str, str] = {}

    async def flaky() -> None:
        nonlocal runs
        runs += 1
        if runs < 3:
            raise RuntimeError("boom")
        await asyncio.sleep(3600)  # healthy forever

    task = asyncio.create_task(
        run_supervised("flaky", flaky, status, base_backoff=0.01, max_backoff=0.02)
    )
    for _ in range(200):
        if runs >= 3:
            break
        await asyncio.sleep(0.01)
    assert runs == 3
    assert status["flaky"] == "running"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_cancellation_propagates_immediately() -> None:
    async def sleeper() -> None:
        await asyncio.sleep(3600)

    task = asyncio.create_task(run_supervised("s", sleeper, {}))
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
