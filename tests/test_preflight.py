from hue_party.preflight import check_music_bus, check_secrets

PACTL_WITH_BUS = "50\tmusic_bus\tPipeWire\tfloat32le 2ch 48000Hz\tIDLE\n51\talsa_output.pci\t...\n"
PACTL_WITHOUT = "51\talsa_output.pci\tPipeWire\tfloat32le 2ch 48000Hz\tRUNNING\n"


def test_music_bus_detected() -> None:
    assert check_music_bus(PACTL_WITH_BUS).ok is True


def test_music_bus_missing_gives_hint() -> None:
    check = check_music_bus(PACTL_WITHOUT)
    assert check.ok is False
    assert "setup-audio.sh" in check.hint


def test_secrets_present_and_missing() -> None:
    ok = check_secrets({"HUE_APP_KEY": "a", "HUE_CLIENT_KEY": "b"})
    assert ok.ok is True
    missing = check_secrets({})
    assert missing.ok is False
    assert "pair" in missing.hint
