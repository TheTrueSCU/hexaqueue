"""Unit tests for DatabaseLeaderElectionAdapter and active-standby controller failover."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from hexaqueue_core.adapters.queue.in_memory import InMemoryJobQueueAdapter
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.adapters.local import LocalSchedulerControllerAdapter
from hexaqueue_server.adapters.storage.leader import (
    DatabaseLeaderElectionAdapter,
    _ensure_utc,
)
from hexaqueue_server.domain.models import RunSubmission


def test_ensure_utc_handles_naive_and_aware_datetimes() -> None:
    """Verify _ensure_utc normalizes naive and timezone-aware timestamps."""
    naive = datetime(2026, 1, 1, 12, 0, 0)  # noqa: DTZ001
    aware = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    norm_naive = _ensure_utc(naive)
    norm_aware = _ensure_utc(aware)
    assert norm_naive.tzinfo == UTC
    assert norm_aware.tzinfo == UTC


@pytest.mark.asyncio
async def test_db_leader_acquire_renew_and_release() -> None:
    """Verify database-backed leader acquisition, renewal, contention, and release."""
    adapter = DatabaseLeaderElectionAdapter()
    elected: list[str] = []
    deposed: list[str] = []
    adapter.on_elected(elected.append)
    adapter.on_deposed(deposed.append)

    initial = await adapter.get_current_leader()
    assert initial is None

    # Renewing when no lease exists returns False
    renew_none = await adapter.renew_leadership("ctrl-1", lease_duration_seconds=10.0)
    assert renew_none is False

    # ctrl-1 acquires lease
    acq_1 = await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=10.0)
    assert acq_1 is True
    assert elected == ["ctrl-1"]

    is_1 = await adapter.is_leader("ctrl-1")
    is_2 = await adapter.is_leader("ctrl-2")
    assert is_1 is True
    assert is_2 is False

    # ctrl-2 is fenced out while ctrl-1 lease is active
    acq_2 = await adapter.acquire_leadership("ctrl-2", lease_duration_seconds=10.0)
    assert acq_2 is False
    renew_2 = await adapter.renew_leadership("ctrl-2", lease_duration_seconds=10.0)
    assert renew_2 is False

    # ctrl-1 re-acquires idempotently and renews
    re_acq_1 = await adapter.acquire_leadership("ctrl-1", lease_duration_seconds=15.0)
    assert re_acq_1 is True
    renew_1 = await adapter.renew_lease("ctrl-1", lease_duration_seconds=20.0)
    assert renew_1 is True

    current = await adapter.get_current_leader()
    assert current is not None
    assert current.leader_id == "ctrl-1"
    assert current.renewal_count == 2

    # Non-leader release is a safe no-op
    await adapter.release_leadership("ctrl-2")
    still_1 = await adapter.is_leader("ctrl-1")
    assert still_1 is True

    # Leader releases lease
    await adapter.release_leadership("ctrl-1")
    assert deposed == ["ctrl-1"]
    after_release = await adapter.get_current_leader()
    assert after_release is None
    adapter.close()


@pytest.mark.asyncio
async def test_db_leader_expiration_and_custom_engine(tmp_path: Path) -> None:
    """Verify database lease expiration triggers deposed callbacks and supports custom engine/URL."""
    db_file = tmp_path / "leader.db"
    url_adapter = DatabaseLeaderElectionAdapter(database_url=f"sqlite:///{db_file}")
    acq_url = await url_adapter.acquire_leadership(
        "node-url", lease_duration_seconds=5.0
    )
    assert acq_url is True
    url_adapter.close()

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    adapter = DatabaseLeaderElectionAdapter(engine=engine, lease_key="custom-key")
    elected: list[str] = []
    deposed: list[str] = []
    adapter.on_elected(elected.append)
    adapter.on_deposed(deposed.append)

    # Acquire short lease for ctrl-a and let it expire
    acq_a = await adapter.acquire_leadership("ctrl-a", lease_duration_seconds=0.01)
    assert acq_a is True
    await asyncio.sleep(0.02)

    # ctrl-b steals expired lease
    acq_b = await adapter.acquire_leadership("ctrl-b", lease_duration_seconds=0.01)
    assert acq_b is True
    assert deposed == ["ctrl-a"]
    assert elected == ["ctrl-a", "ctrl-b"]

    # Wait for ctrl-b to expire and attempt renew
    await asyncio.sleep(0.02)
    renew_expired = await adapter.renew_leadership(
        "ctrl-b", lease_duration_seconds=10.0
    )
    assert renew_expired is False
    assert deposed == ["ctrl-a", "ctrl-b"]

    # Acquire as ctrl-c, let expire, and check get_current_leader cleanup
    acq_c = await adapter.acquire_leadership("ctrl-c", lease_duration_seconds=0.01)
    assert acq_c is True
    await asyncio.sleep(0.02)
    expired_current = await adapter.get_current_leader()
    assert expired_current is None
    assert deposed == ["ctrl-a", "ctrl-b", "ctrl-c"]
    adapter.close()


@pytest.mark.asyncio
async def test_active_standby_controller_failover_with_shared_database() -> None:
    """Verify two controller instances coordinate active/standby failover via shared SQL engine."""
    shared_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    leader_port = DatabaseLeaderElectionAdapter(engine=shared_engine)

    ctrl_primary = LocalSchedulerControllerAdapter(
        queue=InMemoryJobQueueAdapter(),
        leader_election=leader_port,
        controller_id="ctrl-primary",
    )
    ctrl_standby = LocalSchedulerControllerAdapter(
        queue=InMemoryJobQueueAdapter(),
        leader_election=leader_port,
        controller_id="ctrl-standby",
    )

    # Initially neither controller is active leader
    assert ctrl_primary.is_active_leader is False
    assert ctrl_standby.is_active_leader is False

    # Primary acquires lease -> transitions to active leader
    primary_elected = await leader_port.acquire_leadership(
        "ctrl-primary", lease_duration_seconds=10.0
    )
    assert primary_elected is True
    assert ctrl_primary.is_active_leader is True
    assert ctrl_standby.is_active_leader is False

    # Standby rejects mutating run submissions while in follower mode
    sub1 = RunSubmission(
        run_spec=RunSpec(id="run-1", name="r1"),
        jobs=[JobSpec(id="j-1", run_id="run-1", name="j1", command="echo 1")],
    )
    with pytest.raises(HexaqueueError, match="operating in standby mode"):
        await ctrl_standby.submit_run(sub1)

    # Primary accepts submission
    rep1 = await ctrl_primary.submit_run(sub1)
    assert rep1.run_id == "run-1"

    # Shorten primary lease and wait for it to expire so standby can take over
    short_renew = await leader_port.renew_leadership(
        "ctrl-primary", lease_duration_seconds=0.01
    )
    assert short_renew is True
    await asyncio.sleep(0.03)
    standby_elected = await leader_port.acquire_leadership(
        "ctrl-standby", lease_duration_seconds=10.0
    )
    assert standby_elected is True
    assert ctrl_primary.is_active_leader is False
    assert ctrl_standby.is_active_leader is True

    # Standby now accepts run submissions, while primary is fenced out
    sub2 = RunSubmission(
        run_spec=RunSpec(id="run-2", name="r2"),
        jobs=[JobSpec(id="j-2", run_id="run-2", name="j2", command="echo 2")],
    )
    rep2 = await ctrl_standby.submit_run(sub2)
    assert rep2.run_id == "run-2"

    with pytest.raises(HexaqueueError, match="operating in standby mode"):
        await ctrl_primary.submit_run(sub2)
    leader_port.close()
