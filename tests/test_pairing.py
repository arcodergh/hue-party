from pathlib import Path

from hue_party.pairing import pair, write_env


class FakeAPI:
    def __init__(self, host: str) -> None:
        self.host = host
        self.closed = False

    async def pair(self, device_type: str = "x") -> dict[str, str]:
        return {"username": "app-1", "clientkey": "AB" * 16}

    async def close(self) -> None:
        self.closed = True


async def test_pair_returns_creds() -> None:
    creds = await pair("192.168.1.50", api_factory=FakeAPI)
    assert creds == {"username": "app-1", "clientkey": "AB" * 16}


async def test_pair_closes_api_even_on_success() -> None:
    holder: list[FakeAPI] = []

    def factory(host: str) -> FakeAPI:
        api = FakeAPI(host)
        holder.append(api)
        return api

    await pair("h", api_factory=factory)
    assert holder[0].closed


def test_write_env_creates_and_upserts(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nHUE_APP_KEY=old\n")
    write_env(env, {"username": "new-app", "clientkey": "new-key"})
    content = env.read_text()
    assert "OTHER=1" in content
    assert "HUE_APP_KEY=new-app" in content
    assert "HUE_CLIENT_KEY=new-key" in content
    assert "old" not in content
