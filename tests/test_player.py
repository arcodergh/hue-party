import pytest

from hue_party.player import PlayerControl, PlayerError


def fake_runner(responses: dict[tuple[str, ...], tuple[int, str, str]]):
    calls: list[tuple[str, ...]] = []

    async def run(*args: str) -> tuple[int, str, str]:
        calls.append(args)
        return responses.get(args, (0, "", ""))

    return run, calls


async def test_detects_chromium_player_and_sends_command() -> None:
    run, calls = fake_runner({("playerctl", "-l"): (0, "spotify\nchromium.instance42\n", "")})
    player = PlayerControl(runner=run)
    await player.play_pause()
    assert ("playerctl", "-p", "chromium.instance42", "play-pause") in calls


async def test_no_chromium_player_raises_actionable_error() -> None:
    run, _ = fake_runner({("playerctl", "-l"): (0, "spotify\n", "")})
    with pytest.raises(PlayerError, match="YouTube Music"):
        await PlayerControl(runner=run).play_pause()


async def test_now_playing_formats_metadata() -> None:
    run, _ = fake_runner(
        {
            ("playerctl", "-l"): (0, "chromium.instance42\n", ""),
            (
                "playerctl",
                "-p",
                "chromium.instance42",
                "metadata",
                "--format",
                "{{artist}} — {{title}}",
            ): (0, "Daft Punk — One More Time\n", ""),
        }
    )
    assert await PlayerControl(runner=run).now_playing() == "Daft Punk — One More Time"


async def test_now_playing_returns_none_when_player_gone() -> None:
    run, _ = fake_runner({("playerctl", "-l"): (1, "", "No players found")})
    assert await PlayerControl(runner=run).now_playing() is None


async def test_status_returns_playback_state() -> None:
    run, _ = fake_runner(
        {
            ("playerctl", "-l"): (0, "chromium.instance42\n", ""),
            ("playerctl", "-p", "chromium.instance42", "status"): (0, "Playing\n", ""),
        }
    )
    assert await PlayerControl(runner=run).status() == "Playing"


async def test_status_returns_none_when_player_gone() -> None:
    run, _ = fake_runner({("playerctl", "-l"): (1, "", "No players found")})
    assert await PlayerControl(runner=run).status() is None


async def test_art_url_returns_metadata_value() -> None:
    run, _ = fake_runner(
        {
            ("playerctl", "-l"): (0, "chromium.instance42\n", ""),
            ("playerctl", "-p", "chromium.instance42", "metadata", "mpris:artUrl"): (
                0,
                "file:///tmp/art.png\n",
                "",
            ),
        }
    )
    assert await PlayerControl(runner=run).art_url() == "file:///tmp/art.png"


async def test_art_url_returns_none_when_empty_or_unavailable() -> None:
    run, _ = fake_runner(
        {
            ("playerctl", "-l"): (0, "chromium.instance42\n", ""),
            ("playerctl", "-p", "chromium.instance42", "metadata", "mpris:artUrl"): (0, "\n", ""),
        }
    )
    assert await PlayerControl(runner=run).art_url() is None


async def test_command_failure_after_detection_resets_player() -> None:
    """Test that a command failure after successful detection resets _player for re-detection.

    Covers the case where playerctl -l succeeds (player detected) but a subsequent action
    command fails (e.g., player tab closes mid-session), forcing re-detection on next call.
    """
    run, calls = fake_runner(
        {
            ("playerctl", "-l"): (0, "chromium.instance42\n", ""),
            ("playerctl", "-p", "chromium.instance42", "play-pause"): (1, "", "busy"),
        }
    )
    player = PlayerControl(runner=run)
    with pytest.raises(PlayerError):
        await player.play_pause()
    # Verify _player was reset to None after the command failed
    assert player._player is None
    # Verify the calls: detection first, then the failed action
    assert ("playerctl", "-l") in calls
    assert ("playerctl", "-p", "chromium.instance42", "play-pause") in calls


async def test_stop_sends_playerctl_stop() -> None:
    run, calls = fake_runner({("playerctl", "-l"): (0, "chromium.instance42\n", "")})
    await PlayerControl(runner=run).stop()
    assert ("playerctl", "-p", "chromium.instance42", "stop") in calls


async def test_stop_falls_back_to_pause_when_stop_unsupported() -> None:
    run, calls = fake_runner(
        {
            ("playerctl", "-l"): (0, "chromium.instance42\n", ""),
            ("playerctl", "-p", "chromium.instance42", "stop"): (1, "", "not supported"),
        }
    )
    await PlayerControl(runner=run).stop()
    assert ("playerctl", "-p", "chromium.instance42", "pause") in calls


async def test_missing_playerctl_binary_surfaces_as_player_error() -> None:
    async def run(*args: str) -> tuple[int, str, str]:
        raise FileNotFoundError(2, "No such file or directory", "playerctl")

    player = PlayerControl(runner=run)
    with pytest.raises(PlayerError, match="playerctl"):
        await player.play_pause()
    assert await player.status() is None  # callers treating PlayerError as absence work


async def test_pause_and_play_send_commands() -> None:
    run, calls = fake_runner({("playerctl", "-l"): (0, "chromium.instance42\n", "")})
    player = PlayerControl(runner=run)
    await player.pause()
    await player.play()
    assert ("playerctl", "-p", "chromium.instance42", "pause") in calls
    assert ("playerctl", "-p", "chromium.instance42", "play") in calls
