"""Unit tests for ComputeNodeProfile and node lifecycle domain entities."""

import pytest

from hexaqueue_core.domain.node import (
    ComputeNodeProfile,
    NodeHealthState,
    NodeProvisioningTier,
)
from hexaqueue_core.ports.resources import NodeCapacity


def test_compute_node_profile_defaults_and_validation() -> None:
    """Verify default values and required field validation on node profiles."""
    profile = ComputeNodeProfile(node_id="worker-node-alpha")

    n_id = profile.node_id
    tier = profile.tier
    health = profile.health_state
    cached = profile.cached_collateral_hashes
    active = profile.active_job_ids
    is_avail = profile.is_available

    assert n_id == "worker-node-alpha"
    assert tier == NodeProvisioningTier.STATIC
    assert health == NodeHealthState.HEALTHY
    assert len(cached) == 0
    assert len(active) == 0
    assert is_avail is True

    with pytest.raises(ValueError, match="node_id cannot be empty"):
        ComputeNodeProfile(node_id="  ")


def test_compute_node_profile_state_transitions() -> None:
    """Verify transitions across HEALTHY, UNHEALTHY, DEAD, and DRAINED states."""
    profile = ComputeNodeProfile(node_id="worker-node-1")
    assert profile.health_state == NodeHealthState.HEALTHY

    # Missed heartbeat -> UNHEALTHY
    unhealthy = profile.mark_unhealthy()
    u_health = unhealthy.health_state
    u_avail = unhealthy.is_available
    assert u_health == NodeHealthState.UNHEALTHY
    assert u_avail is False

    # Pulse recovered -> HEALTHY
    recovered = unhealthy.touch_heartbeat()
    r_health = recovered.health_state
    assert r_health == NodeHealthState.HEALTHY

    # Heartbeat timeout -> DEAD
    dead = unhealthy.mark_dead()
    d_health = dead.health_state
    assert d_health == NodeHealthState.DEAD

    # Drain active workloads -> DRAINED
    with_jobs = dead.assign_job("job-1").assign_job("job-2")
    job_count = len(with_jobs.active_job_ids)
    assert job_count == 2

    drained = with_jobs.mark_drained()
    dr_health = drained.health_state
    dr_jobs = len(drained.active_job_ids)
    assert dr_health == NodeHealthState.DRAINED
    assert dr_jobs == 0


def test_compute_node_profile_cached_collateral_and_jobs() -> None:
    """Verify warm cache hashing index and job tracking."""
    capacity = NodeCapacity(
        available_cpus=8,
        available_ram_mb=16384,
        node_id="worker-node-1",
        total_cpus=8,
        total_ram_mb=16384,
    )
    profile = ComputeNodeProfile(
        capacity=capacity,
        node_id="worker-node-1",
        tier=NodeProvisioningTier.EPHEMERAL,
    )

    p_tier = profile.tier
    assert p_tier == NodeProvisioningTier.EPHEMERAL

    # Add cached collateral hash
    sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    updated = profile.add_cached_hash(sha)
    has_hash = updated.has_cached_collateral(sha)
    has_missing = updated.has_cached_collateral("unknown-hash")

    assert has_hash is True
    assert has_missing is False

    # Assign and release job
    assigned = updated.assign_job("job-xyz")
    is_in_jobs = "job-xyz" in assigned.active_job_ids
    assert is_in_jobs is True

    released = assigned.release_job("job-xyz")
    is_released = "job-xyz" not in released.active_job_ids
    assert is_released is True
