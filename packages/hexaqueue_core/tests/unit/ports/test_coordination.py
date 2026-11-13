"""Tests for LeaderElectionPort interface."""

import inspect

import pytest

from hexaqueue_core.domain.coordination import LeaderLease
from hexaqueue_core.ports.coordination import LeaderElectionPort


class _StubLeaderPort(LeaderElectionPort):
    """Concrete stub implementation of LeaderElectionPort for testing concrete helpers."""

    def __init__(self) -> None:
        super().__init__()
        self.renewed_with: tuple[str, float] | None = None

    async def acquire_leadership(
        self, candidate_id: str, lease_duration_seconds: float = 15.0
    ) -> bool:
        return True

    async def renew_leadership(
        self, candidate_id: str, lease_duration_seconds: float = 15.0
    ) -> bool:
        self.renewed_with = (candidate_id, lease_duration_seconds)
        return True

    async def release_leadership(self, candidate_id: str) -> None:
        return None

    async def is_leader(self, candidate_id: str) -> bool:
        return True

    async def get_current_leader(self) -> LeaderLease | None:
        return None


def test_leader_election_port_is_abstract() -> None:
    """Verify LeaderElectionPort is an abstract interface."""
    is_abs = inspect.isabstract(LeaderElectionPort)
    assert is_abs is True
    assert "acquire_leadership" in LeaderElectionPort.__abstractmethods__


@pytest.mark.asyncio
async def test_leader_election_port_renew_lease_and_callbacks() -> None:
    """Verify renew_lease alias and lifecycle callbacks on LeaderElectionPort."""
    port = _StubLeaderPort()
    events: list[tuple[str, str]] = []

    def sync_elected(cid: str) -> None:
        events.append(("sync_elected", cid))

    def sync_deposed(cid: str) -> None:
        events.append(("sync_deposed", cid))

    port.on_elected(sync_elected)
    port.on_deposed(sync_deposed)

    renewed = await port.renew_lease("node-1", lease_duration_seconds=20.0)
    assert renewed is True
    assert port.renewed_with == ("node-1", 20.0)

    await port._notify_elected("node-1")
    await port._notify_deposed("node-1")

    assert events == [
        ("sync_elected", "node-1"),
        ("sync_deposed", "node-1"),
    ]
