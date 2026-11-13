"""Unit tests for LeaderLease coordination domain entity."""

import asyncio
import concurrent.futures
from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.domain.coordination import (
    CrossLoopAsyncCondition,
    CrossLoopAsyncLock,
    LeaderLease,
)


def test_leader_lease_creation_and_expiration() -> None:
    """Verify leader lease expiration logic and validity checking."""
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=10)
    lease = LeaderLease(
        acquired_at=now,
        expires_at=expires,
        leader_id="controller-01",
        lease_duration_seconds=10.0,
    )

    lead_id = lease.leader_id
    renewals = lease.renewal_count
    not_expired = lease.is_expired(now)
    past_expired = lease.is_expired(now + timedelta(seconds=11))

    assert lead_id == "controller-01"
    assert renewals == 0
    assert not_expired is False
    assert past_expired is True


def test_leader_lease_renewal() -> None:
    """Verify renewal extends expiration deadline and increments counter."""
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=5)
    lease = LeaderLease(
        acquired_at=now,
        expires_at=expires,
        leader_id="controller-01",
        lease_duration_seconds=5.0,
    )

    renewed = lease.renew(duration_seconds=15.0)
    count = renewed.renewal_count
    duration = renewed.lease_duration_seconds
    is_exp = renewed.is_expired(now + timedelta(seconds=10))

    assert count == 1
    assert duration == 15.0
    assert is_exp is False


def test_leader_lease_validation_errors() -> None:
    """Verify validation when leader_id is blank or expiration precedes acquisition."""
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="leader_id cannot be empty"):
        LeaderLease(
            acquired_at=now,
            expires_at=now + timedelta(seconds=10),
            leader_id="   ",
            lease_duration_seconds=10.0,
        )

    with pytest.raises(ValueError, match="cannot precede acquired_at"):
        LeaderLease(
            acquired_at=now,
            expires_at=now - timedelta(seconds=10),
            leader_id="controller-1",
            lease_duration_seconds=10.0,
        )


@pytest.mark.asyncio
async def test_cross_loop_async_lock_and_condition() -> None:
    """Verify CrossLoopAsyncLock and CrossLoopAsyncCondition work across multiple event loops."""
    lock = CrossLoopAsyncLock()
    initial_locked = lock.locked()
    assert initial_locked is False

    async with lock:
        inside_locked = lock.locked()
        assert inside_locked is True

    after_locked = lock.locked()
    assert after_locked is False

    cond = CrossLoopAsyncCondition(lock=lock)
    acq = await cond.acquire()
    assert acq is True
    cond.notify(0)
    cond.notify(1)
    cond.release()

    def notify_from_worker_loop() -> bool:
        async def _notify() -> bool:
            await asyncio.sleep(0.01)
            async with cond:
                cond.notify_all()
            return True

        return asyncio.run(_notify())

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        fut = pool.submit(notify_from_worker_loop)
        async with cond:
            waited = await asyncio.wait_for(cond.wait(), timeout=1.0)
            assert waited is True
        worker_done = fut.result()
        assert worker_done is True
