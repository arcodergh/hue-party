from hue_party.delay import DelayBuffer
from hue_party.models import ChannelColor, LightFrame
from hue_party.streamer import LightStreamer


class FakeSession:
    def __init__(self) -> None:
        self.sent: list[list[object]] = []

    def send(self, commands: list[object]) -> None:
        self.sent.append(commands)


def make_streamer(now: float) -> tuple[LightStreamer, FakeSession, list[float]]:
    session = FakeSession()
    clock_value = [now]
    streamer = LightStreamer(session, DelayBuffer(), clock=lambda: clock_value[0])
    return streamer, session, clock_value


def test_tick_sends_nothing_before_offset() -> None:
    streamer, session, _ = make_streamer(now=100.0)
    streamer.offset_ms = 1000
    streamer.submit(LightFrame(timestamp=100.0, channels={0: ChannelColor(65535, 0, 0)}))
    assert streamer.tick() is False
    assert session.sent == []


def test_tick_sends_newest_due_frame_and_drops_stale() -> None:
    streamer, session, clock = make_streamer(now=100.0)
    streamer.offset_ms = 0
    streamer.submit(LightFrame(timestamp=99.0, channels={0: ChannelColor(1, 1, 1)}))
    streamer.submit(
        LightFrame(
            timestamp=99.5,
            channels={0: ChannelColor(2, 2, 2), 1: ChannelColor(3, 3, 3)},
        )
    )
    assert streamer.tick() is True
    assert len(session.sent) == 1  # only the newest frame went out
    commands = session.sent[0]
    assert len(commands) == 2
    assert {c.channel_id for c in commands} == {0, 1}  # type: ignore[attr-defined]
    reds = {c.channel_id: c.red for c in commands}  # type: ignore[attr-defined]
    assert reds[0] == 2 and reds[1] == 3


async def test_reconnect_now_swaps_session_for_subsequent_ticks() -> None:
    old, new = FakeSession(), FakeSession()

    async def reconnect() -> FakeSession:
        return new

    buffer = DelayBuffer()
    streamer = LightStreamer(old, buffer, clock=lambda: 100.0, reconnect=reconnect)
    await streamer.reconnect_now()
    buffer.push(LightFrame(timestamp=99.0, channels={0: ChannelColor(1, 1, 1)}))
    streamer.tick()
    assert old.sent == []
    assert len(new.sent) == 1


async def test_streamer_reconnects_after_send_failure() -> None:
    good = FakeSession()

    class BadSession:
        def send(self, commands: list[object]) -> None:
            raise ConnectionError("stream lost")

    async def reconnect() -> FakeSession:
        return good

    buffer = DelayBuffer()
    streamer = LightStreamer(BadSession(), buffer, clock=lambda: 100.0, reconnect=reconnect)
    buffer.push(LightFrame(timestamp=99.0, channels={0: ChannelColor(1, 1, 1)}))
    await streamer.run_once()  # helper: one iteration of run()'s loop body, for tests
    buffer.push(LightFrame(timestamp=99.5, channels={0: ChannelColor(2, 2, 2)}))
    await streamer.run_once()
    assert len(good.sent) == 1
