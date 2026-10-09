"""Unit tests for InMemoryLeaderElectionAdapter."""

import asyncio

import pytest

from hexaqueue_core.adapters.coordination.in_memory import (
    InMemoryLeaderElectionAdapter,
)


@pytest.mark.asyncio
async def test_acquire_and_release_leadership() -> None:
    """Verify leadership acquisition, leader check, and voluntary release."""
    adapter = InMemoryLeaderElectionAdapter()

    # Initial state: no leader
    initial_leader = await adapter.get_current_leader()
    assert initial_leader is None

    # Candidate 1 acquires leadership for 10 seconds
    acquired_1 = await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=10.0)
    assert acquired_1 is True

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

    released_leader = await adapter.get_current_leader()
    assert released_leader is None

    # Candidate 2 can now acquire leadership
    acquired_2_after = await adapter.acquire_leadership(
        "ctrl-2", lease_duration_seconds=10.0
    )
    assert acquired_2_after is True
    is_c2_now = await adapter.is_leader("ctrl-2")
    assert is_c2_now is True


@pytest.mark.asyncio
async def test_renew_leadership() -> None:
    """Verify renewal behavior for leader vs non-leader."""
    adapter = InMemoryLeaderElectionAdapter()

    # Acquire initial lease
    await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=5.0)

    # Leader renews successfully
    renew_success = await adapter.renew_leadership(
        "ctrl-1", lease_duration_seconds=15.0
    )
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


@pytest.mark.asyncio
async def test_lease_expiration_allows_new_leader() -> None:
    """Verify that an expired lease automatically allows another candidate to assume leadership."""
    adapter = InMemoryLeaderElectionAdapter()

    # Acquire very short lease
    await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=0.01)

    # Wait for expiration
    await asyncio.sleep(0.02)

    # Lease should now be detected as expired
    active_leader = await adapter.get_current_leader()
    assert active_leader is None

    is_c1 = await adapter.is_leader("ctrl-1")
    assert is_c1 is False

    # Candidate 2 acquires the expired lease
    acquired_2 = await adapter.acquire_leadership("ctrl-2", lease_duration_seconds=10.0)
    assert acquired_2 is True

    new_leader = await adapter.get_current_leader()
    assert new_leader is not None
    assert new_leader.leader_id == "ctrl-2"


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
