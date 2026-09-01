import asyncio

from hue_party.watchdog import STREAM_LIVE, STREAM_STOPPED, StreamWatchdog


class Harness:
    """Watchdog wired to in-memory fakes with a manual clock."""

    def __init__(self, *, grace: float = 15.0) -> None:
        self.playing: str | None = "Playing"
        self.remote: tuple[str, str] = ("active", "us")
        self.reclaims = 0
        self.suspends = 0
        self.now = 0.0
        self.status: dict[str, str] = {}

        async def player_status() -> str | None:
            return self.playing

        async def remote_status() -> tuple[str, str]:
            return self.remote

        async def reclaim() -> None:
            self.reclaims += 1
            self.remote = ("active", "us")

        async def suspend() -> None:
            self.suspends += 1
            self.remote = ("inactive", "")

        self.party_starts = 0
        self.party_stops = 0
        self.party_hook_error: Exception | None = None

        async def on_party_start() -> None:
            if self.party_hook_error is not None:
                raise self.party_hook_error
            self.party_starts += 1

        async def on_party_stop() -> None:
            self.party_stops += 1

        self.watchdog = StreamWatchdog(
            player_status=player_status,
            remote_status=remote_status,
            reclaim=reclaim,
            suspend=suspend,
            on_party_start=on_party_start,
            on_party_stop=on_party_stop,
            status=self.status,
            music_stop_grace_s=grace,
            clock=lambda: self.now,
        )


async def test_healthy_stream_is_left_alone() -> None:
    h = Harness()
    await h.watchdog.poll_once()
    assert h.reclaims == 0
    assert h.suspends == 0
    assert h.status["stream"] == STREAM_LIVE


async def test_reclaims_when_bridge_reports_inactive_while_music_plays() -> None:
    h = Harness()
    h.remote = ("inactive", "")  # e.g. someone tapped stop in the Hue app
    await h.watchdog.poll_once()
    assert h.reclaims == 1


async def test_reclaims_when_another_streamer_takes_over() -> None:
    h = Harness()
    await h.watchdog.poll_once()  # calibrates: records "us" as our streamer rid
    h.remote = ("active", "them")
    await h.watchdog.poll_once()
    assert h.reclaims == 1


async def test_suspends_only_after_grace_when_music_stops() -> None:
    h = Harness(grace=15.0)
    await h.watchdog.poll_once()
    h.playing = "Paused"
    h.now = 10.0
    await h.watchdog.poll_once()
    assert h.suspends == 0  # inside grace: track change / brief pause must not kill lights
    h.now = 20.0
    await h.watchdog.poll_once()
    assert h.suspends == 1
    assert h.status["stream"] == STREAM_STOPPED
    h.now = 30.0
    await h.watchdog.poll_once()
    assert h.suspends == 1  # already suspended; don't stop again


async def test_suspended_stream_is_not_reclaimed_while_music_stays_stopped() -> None:
    h = Harness(grace=15.0)
    h.playing = None  # player gone entirely (Chrome closed) counts as stopped
    h.now = 20.0
    await h.watchdog.poll_once()
    assert h.suspends == 1
    h.now = 60.0
    await h.watchdog.poll_once()  # Hue app is free to run its own sync now
    assert h.reclaims == 0


async def test_resumes_stream_when_music_plays_again() -> None:
    h = Harness(grace=15.0)
    h.playing = "Paused"
    h.now = 20.0
    await h.watchdog.poll_once()
    assert h.suspends == 1
    h.playing = "Playing"
    h.now = 25.0
    await h.watchdog.poll_once()
    assert h.reclaims == 1
    assert h.status["stream"] == STREAM_LIVE


async def test_party_start_fires_once_when_music_first_plays() -> None:
    h = Harness()
    await h.watchdog.poll_once()
    await h.watchdog.poll_once()
    assert h.party_starts == 1
    assert h.party_stops == 0


async def test_party_stop_fires_on_suspend_and_start_fires_again_on_resume() -> None:
    h = Harness(grace=15.0)
    await h.watchdog.poll_once()
    h.playing = "Paused"
    h.now = 20.0
    await h.watchdog.poll_once()
    assert h.party_stops == 1
    h.playing = "Playing"
    h.now = 25.0
    await h.watchdog.poll_once()
    assert h.party_starts == 2


async def test_party_hook_failure_does_not_break_stream_management() -> None:
    h = Harness()
    h.party_hook_error = ConnectionError("bridge offline")
    await h.watchdog.poll_once()  # must not raise
    assert h.status["stream"] == STREAM_LIVE


async def test_run_keeps_polling_after_a_poll_error() -> None:
    calls = 0

    async def flaky_player_status() -> str | None:
        nonlocal calls
        calls += 1
        raise ConnectionError("bridge unreachable")

    async def unused() -> None:
        raise AssertionError("must not be called")

    async def no_remote() -> tuple[str, str]:
        return ("active", "us")

    watchdog = StreamWatchdog(
        player_status=flaky_player_status,
        remote_status=no_remote,
        reclaim=unused,
        suspend=unused,
        status={},
        poll_s=0.0,
        clock=lambda: 0.0,
    )
    task = asyncio.create_task(watchdog.run())
    while calls < 3:  # a transient poll failure must not end the loop
        await asyncio.sleep(0)
    task.cancel()


async def test_stop_party_suspends_immediately_and_fires_party_stop() -> None:
    h = Harness(grace=15.0)
    await h.watchdog.poll_once()  # music playing: party on, stream live
    await h.watchdog.stop_party()
    assert h.suspends == 1  # no 15s grace: stop means now
    assert h.party_stops == 1
    assert h.status["stream"] == STREAM_STOPPED
    await h.watchdog.stop_party()
    assert h.suspends == 1  # idempotent


async def test_party_resumes_after_stop_when_music_plays_again() -> None:
    h = Harness(grace=15.0)
    await h.watchdog.poll_once()
    await h.watchdog.stop_party()
    h.now = 10.0
    await h.watchdog.poll_once()  # music still "Playing" per player: party comes back
    assert h.reclaims == 1
    assert h.party_starts == 2


async def test_stop_party_fires_stop_hook_even_when_party_never_started_here() -> None:
    # A restart mid-party loses _party_on but leaves lights off on the bridge;
    # the hook must always run so an orphaned blackout snapshot gets restored.
    h = Harness(grace=15.0)
    h.playing = None
    await h.watchdog.stop_party()
    assert h.party_stops == 1


async def test_grace_suspend_fires_stop_hook_even_without_party() -> None:
    h = Harness(grace=15.0)
    h.playing = None
    h.now = 20.0
    await h.watchdog.poll_once()
    assert h.suspends == 1
    assert h.party_stops == 1


async def test_stream_required_holds_the_stream_without_music() -> None:
    # Calibration needs lights while music is paused: the hold keeps the stream up.
    h = Harness(grace=15.0)
    h.watchdog._stream_required = lambda: True
    h.playing = None
    h.now = 30.0  # far past the grace period
    await h.watchdog.poll_once()
    assert h.suspends == 0
    assert h.status["stream"] == STREAM_LIVE


async def test_stream_required_reclaims_a_suspended_stream() -> None:
    h = Harness(grace=15.0)
    h.playing = None
    h.now = 20.0
    await h.watchdog.poll_once()
    assert h.suspends == 1  # normal idle stop
    h.watchdog._stream_required = lambda: True  # calibration begins
    h.now = 25.0
    await h.watchdog.poll_once()
    assert h.reclaims == 1
    assert h.status["stream"] == STREAM_LIVE
