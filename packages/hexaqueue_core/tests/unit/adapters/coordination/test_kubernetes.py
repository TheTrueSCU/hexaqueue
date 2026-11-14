"""Unit tests for KubernetesLeaseLeaderAdapter."""

import asyncio
from typing import Any

import pytest

from hexaqueue_core.adapters.coordination.kubernetes import (
    KubernetesLeaseLeaderAdapter,
)


@pytest.mark.asyncio
async def test_k8s_lease_acquire_renew_release_lifecycle() -> None:
    """Verify Kubernetes Lease leader acquisition, renewal, contention, and voluntary release."""
    adapter = KubernetesLeaseLeaderAdapter(
        lease_name="hexaqueue-leader",
        namespace="hexaqueue-system",
    )
    elected: list[str] = []
    deposed: list[str] = []
    adapter.on_elected(elected.append)
    adapter.on_deposed(deposed.append)

    initial = await adapter.get_current_leader()
    assert initial is None

    # Renewing before acquisition returns False
    renew_before = await adapter.renew_leadership("pod-a", lease_duration_seconds=10.0)
    assert renew_before is False

    # pod-a acquires lease
    acq_a = await adapter.acquire_leadership("pod-a", lease_duration_seconds=10.0)
    assert acq_a is True
    assert elected == ["pod-a"]

    is_a = await adapter.is_leader("pod-a")
    is_b = await adapter.is_leader("pod-b")
    assert is_a is True
    assert is_b is False

    # pod-b blocked while pod-a lease is valid
    acq_b = await adapter.acquire_leadership("pod-b", lease_duration_seconds=10.0)
    assert acq_b is False
    renew_b = await adapter.renew_leadership("pod-b", lease_duration_seconds=10.0)
    assert renew_b is False

    # pod-a re-acquires idempotently and renews
    re_acq_a = await adapter.acquire_leadership("pod-a", lease_duration_seconds=15.0)
    assert re_acq_a is True
    renew_a = await adapter.renew_lease("pod-a", lease_duration_seconds=20.0)
    assert renew_a is True

    current = await adapter.get_current_leader()
    assert current is not None
    assert current.leader_id == "pod-a"
    assert current.renewal_count == 2

    # Non-leader release is a no-op
    await adapter.release_leadership("pod-b")
    still_a = await adapter.is_leader("pod-a")
    assert still_a is True

    # Leader releases lease
    await adapter.release_leadership("pod-a")
    assert deposed == ["pod-a"]
    after_release = await adapter.get_current_leader()
    assert after_release is None


@pytest.mark.asyncio
async def test_k8s_lease_expiration_and_failover() -> None:
    """Verify expired Kubernetes Lease triggers deposed callbacks and failover to standby pod."""
    adapter = KubernetesLeaseLeaderAdapter()
    elected: list[str] = []
    deposed: list[str] = []
    adapter.on_elected(elected.append)
    adapter.on_deposed(deposed.append)

    # pod-1 acquires short lease and lets it expire
    acq_1 = await adapter.acquire_leadership("pod-1", lease_duration_seconds=0.01)
    assert acq_1 is True
    await asyncio.sleep(0.02)

    # pod-2 takes over expired lease
    acq_2 = await adapter.acquire_leadership("pod-2", lease_duration_seconds=0.01)
    assert acq_2 is True
    assert deposed == ["pod-1"]
    assert elected == ["pod-1", "pod-2"]

    # Wait for pod-2 lease to expire, then attempt renew
    await asyncio.sleep(0.02)
    renew_expired = await adapter.renew_leadership("pod-2", lease_duration_seconds=10.0)
    assert renew_expired is False
    assert deposed == ["pod-1", "pod-2"]

    # Acquire again as pod-3, let expire, and check get_current_leader cleanup
    acq_3 = await adapter.acquire_leadership("pod-3", lease_duration_seconds=0.01)
    assert acq_3 is True
    await asyncio.sleep(0.02)
    expired_current = await adapter.get_current_leader()
    assert expired_current is None
    assert deposed == ["pod-1", "pod-2", "pod-3"]


def test_k8s_parse_lease_doc_edge_cases() -> None:
    """Verify _parse_lease_doc handles empty or missing spec fields safely."""
    none_res = KubernetesLeaseLeaderAdapter._parse_lease_doc(None)
    assert none_res is None

    empty_spec_res = KubernetesLeaseLeaderAdapter._parse_lease_doc({"spec": {}})
    assert empty_spec_res is None

    minimal_doc: dict[str, Any] = {
        "spec": {
            "holderIdentity": "pod-minimal",
        }
    }
    parsed = KubernetesLeaseLeaderAdapter._parse_lease_doc(minimal_doc)
    assert parsed is not None
    assert parsed.leader_id == "pod-minimal"
