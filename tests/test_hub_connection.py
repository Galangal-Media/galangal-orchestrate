"""Tests for agent-identity protection in the hub ConnectionManager."""

import pytest

from galangal_hub.connection import ConnectionManager
from galangal_hub.models import AgentInfo


class _WS:
    """Minimal fake WebSocket; send_text raises when the socket is 'dead'."""

    def __init__(self, alive: bool = True):
        self.alive = alive
        self.sent: list[str] = []

    async def send_text(self, msg: str) -> None:
        if not self.alive:
            raise RuntimeError("socket closed")
        self.sent.append(msg)


def _info(agent_id="a"):
    return AgentInfo(
        agent_id=agent_id,
        hostname="h",
        project_name="p",
        project_path="/p",
        agent_name="n",
    )


@pytest.mark.asyncio
async def test_first_registration_succeeds():
    m = ConnectionManager()
    assert await m.connect("a", _WS(), _info()) is True


@pytest.mark.asyncio
async def test_live_connection_not_displaced():
    m = ConnectionManager()
    await m.connect("a", _WS(alive=True), _info())
    # A second registration for the same id while the first is alive is refused.
    assert await m.connect("a", _WS(alive=True), _info()) is False


@pytest.mark.asyncio
async def test_dead_connection_taken_over():
    m = ConnectionManager()
    await m.connect("a", _WS(alive=False), _info())  # registers (nothing existing)
    # The existing socket is dead, so a legitimate reconnect takes over.
    new_ws = _WS(alive=True)
    assert await m.connect("a", new_ws, _info()) is True
    assert m.get_agent("a") is not None
