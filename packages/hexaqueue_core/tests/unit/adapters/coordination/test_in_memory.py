"""Unit tests for InMemoryLeaderElectionAdapter."""

import asyncio

import pytest

from hexaqueue_core.adapters.coordination.in_memory import (
    InMemoryLeaderAdapter,
    InMemoryLeaderElectionAdapter,
)


@pytest.mark.asyncio
async def test_acquire_and_release_leadership() -> None:
    """Verify leadership acquisition, leader check, callbacks, and voluntary release."""
    adapter = InMemoryLeaderAdapter()
    elected_events: list[str] = []
    deposed_events: list[str] = []
    adapter.on_elected(elected_events.append)
    adapter.on_deposed(deposed_events.append)

    # Initial state: no leader
    initial_leader = await adapter.get_current_leader()
    assert initial_leader is None

    # Candidate 1 acquires leadership for 10 seconds
    acquired_1 = await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=10.0)
    assert acquired_1 is True
    assert elected_events == ["ctrl-1"]

    is_c1 = await adapter.is_leader("ctrl-1")
    is_c2 = await adapter.is_leader("ctrl-2")
    assert is_c1 is True
    assert is_c2 is False

    current_leader = await adapter.get_current_leader()
    assert current_leader is not None
    assert current_leader.leader_id == "ctrl-1"

    # Candidate 2 attempts acquisition while lease is active
    acquired_2 = await adapter.acquire_leadership("ctrl-2", lease_duration_seconds=10.0)
    assert acquired_2 is False

    # Candidate 1 voluntarily releases leadership
    await adapter.release_leadership("ctrl-1")
    assert deposed_events == ["ctrl-1"]

    released_leader = await adapter.get_current_leader()
    assert released_leader is None

    # Candidate 2 can now acquire leadership
    acquired_2_after = await adapter.acquire_leadership(
        "ctrl-2", lease_duration_seconds=10.0
    )
    assert acquired_2_after is True
    assert elected_events == ["ctrl-1", "ctrl-2"]
    is_c2_now = await adapter.is_leader("ctrl-2")
    assert is_c2_now is True


@pytest.mark.asyncio
async def test_renew_leadership() -> None:
    """Verify renewal behavior for leader vs non-leader and expired leases."""
    adapter = InMemoryLeaderElectionAdapter()
    deposed: list[str] = []
    adapter.on_deposed(deposed.append)

    # Renewing when no lease exists returns False
    renew_none = await adapter.renew_leadership("ctrl-1", lease_duration_seconds=5.0)
    assert renew_none is False

    # Acquire initial lease
    await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=5.0)

    # Leader renews successfully via renew_lease alias
    renew_success = await adapter.renew_lease("ctrl-1", lease_duration_seconds=15.0)
    assert renew_success is True

    leader = await adapter.get_current_leader()
    assert leader is not None
    assert leader.renewal_count == 1
    assert leader.lease_duration_seconds == 15.0

    # Non-leader cannot renew
    renew_fail = await adapter.renew_leadership("ctrl-2", lease_duration_seconds=15.0)
    assert renew_fail is False

    # Re-acquisition by existing leader acts as idempotent renewal
    re_acquire = await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=20.0)
    assert re_acquire is True
    updated_leader = await adapter.get_current_leader()
    assert updated_leader is not None
    assert updated_leader.renewal_count == 2

    # Expired lease fails renewal and fires deposed callback
    await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=0.01)
    await asyncio.sleep(0.02)
    renew_expired = await adapter.renew_leadership("ctrl-1", lease_duration_seconds=5.0)
    assert renew_expired is False
    assert deposed == ["ctrl-1"]


@pytest.mark.asyncio
async def test_lease_expiration_allows_new_leader() -> None:
    """Verify that an expired lease automatically allows another candidate to assume leadership."""
    adapter = InMemoryLeaderElectionAdapter()
    deposed: list[str] = []
    elected: list[str] = []
    adapter.on_deposed(deposed.append)
    adapter.on_elected(elected.append)

    # Acquire very short lease
    await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=0.01)

    # Wait for expiration
    await asyncio.sleep(0.02)

    # Candidate 2 directly acquires expired lease (triggering deposed for ctrl-1)
    acquired_2 = await adapter.acquire_leadership("ctrl-2", lease_duration_seconds=10.0)
    assert acquired_2 is True
    assert deposed == ["ctrl-1"]
    assert elected == ["ctrl-1", "ctrl-2"]

    new_leader = await adapter.get_current_leader()
    assert new_leader is not None
    assert new_leader.leader_id == "ctrl-2"

    # Let ctrl-2 expire and verify get_current_leader detects expiration
    await adapter.acquire_leadership("ctrl-2", lease_duration_seconds=0.01)
    await asyncio.sleep(0.02)
    active_leader = await adapter.get_current_leader()
    assert active_leader is None
    assert deposed == ["ctrl-1", "ctrl-2"]


@pytest.mark.asyncio
async def test_concurrent_acquisition_contention() -> None:
    """Verify mutual exclusion when multiple candidates compete concurrently."""
    adapter = InMemoryLeaderElectionAdapter()

    async def attempt(cid: str) -> bool:
        return await adapter.acquire_leadership(cid, lease_duration_seconds=10.0)

    results = await asyncio.gather(
        attempt("node-a"),
        attempt("node-b"),
        attempt("node-c"),
        attempt("node-d"),
    )

    success_count = sum(1 for r in results if r is True)
    assert success_count == 1
