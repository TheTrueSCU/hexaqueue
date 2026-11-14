"""Tests for WarmCachePlacementEngine and PlacementDecision."""

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.node import (
    ComputeNodeProfile,
    NodeHealthState,
    NodeProvisioningTier,
)
from hexaqueue_core.ports.resources import NodeCapacity
from hexaqueue_server.domain.placement import (
    PlacementDecision,
    WarmCachePlacementEngine,
)


def test_placement_decision_model() -> None:
    """Verify PlacementDecision domain model invariants and defaults."""
    decision = PlacementDecision(
        reason="Test selection",
        selected_node_id="node-1",
        tier=NodeProvisioningTier.STATIC,
        total_required=2,
        warm_hits=2,
        hit_ratio=1.0,
    )
    sel_id = decision.selected_node_id
    assert sel_id == "node-1"
    assert decision.tier == NodeProvisioningTier.STATIC
    assert decision.warm_hits == 2
    assert decision.hit_ratio == 1.0
    assert decision.should_burst_ephemeral is False


def test_placement_prefers_static_node_with_warm_cache() -> None:
    """Verify engine selects static node with 100% warm collateral hits over empty node."""
    engine = WarmCachePlacementEngine(burst_backlog_threshold=5)

    job = JobSpec(
        id="job-1",
        run_id="run-1",
        name="test-job",
        command="python",
        collateral_ids=["col-dataset-1", "col-model-weights"],
    )
    hash_map = {
        "col-dataset-1": "sha256-dataset",
        "col-model-weights": "sha256-weights",
    }

    node_cold = ComputeNodeProfile(
        node_id="node-cold",
        tier=NodeProvisioningTier.STATIC,
        cached_collateral_hashes=frozenset(["other-hash"]),
    )
    node_warm = ComputeNodeProfile(
        node_id="node-warm",
        tier=NodeProvisioningTier.STATIC,
        cached_collateral_hashes=frozenset(["sha256-dataset", "sha256-weights"]),
    )

    decision = engine.evaluate_placement(
        job=job,
        nodes=[node_cold, node_warm],
        collateral_hash_map=hash_map,
        backlog_size=0,
    )
    sel_id = decision.selected_node_id
    assert sel_id == "node-warm"
    assert decision.tier == NodeProvisioningTier.STATIC
    assert decision.warm_hits == 2
    assert decision.total_required == 2
    assert decision.hit_ratio == 1.0
    assert decision.should_burst_ephemeral is False


def test_placement_falls_back_to_ephemeral_when_static_saturated() -> None:
    """Verify engine falls back to ephemeral node when static node is at full capacity."""
    engine = WarmCachePlacementEngine(burst_backlog_threshold=5)

    job = JobSpec(
        id="job-burst",
        run_id="run-1",
        name="burst-job",
        command="python",
        collateral_ids=[],
    )

    static_full = ComputeNodeProfile(
        node_id="node-static-full",
        tier=NodeProvisioningTier.STATIC,
        capacity=NodeCapacity(
            node_id="node-static-full",
            total_cpus=4,
            available_cpus=0,
            total_ram_mb=8192,
            available_ram_mb=0,
        ),
        active_job_ids=frozenset(["running-job-1"]),
    )
    ephemeral_avail = ComputeNodeProfile(
        node_id="node-ephemeral-1",
        tier=NodeProvisioningTier.EPHEMERAL,
        capacity=NodeCapacity(
            node_id="node-ephemeral-1",
            total_cpus=4,
            available_cpus=4,
            total_ram_mb=8192,
            available_ram_mb=8192,
        ),
        active_job_ids=frozenset([]),
    )

    decision = engine.evaluate_placement(
        job=job,
        nodes=[static_full, ephemeral_avail],
        backlog_size=1,
    )
    sel_id = decision.selected_node_id
    assert sel_id == "node-ephemeral-1"
    assert decision.tier == NodeProvisioningTier.EPHEMERAL
    assert decision.should_burst_ephemeral is False


def test_placement_recommends_cloud_burst_when_all_saturated_and_high_backlog() -> None:
    """Verify engine signals should_burst_ephemeral when backlog exceeds threshold."""
    engine = WarmCachePlacementEngine(burst_backlog_threshold=3)

    job = JobSpec(
        id="job-starved",
        run_id="run-1",
        name="starved-job",
        command="python",
    )

    static_full = ComputeNodeProfile(
        node_id="node-static",
        tier=NodeProvisioningTier.STATIC,
        capacity=NodeCapacity(
            node_id="node-static",
            total_cpus=4,
            available_cpus=0,
            total_ram_mb=8192,
            available_ram_mb=0,
        ),
        active_job_ids=frozenset(["j-1"]),
    )

    decision = engine.evaluate_placement(
        job=job,
        nodes=[static_full],
        backlog_size=4,
    )
    sel_id = decision.selected_node_id
    assert sel_id is None
    assert decision.should_burst_ephemeral is True
    assert "Recommend dynamic cloud bursting" in decision.reason


def test_placement_excludes_unhealthy_or_dead_nodes() -> None:
    """Verify unhealthy or dead nodes are never considered for placement."""
    engine = WarmCachePlacementEngine()

    job = JobSpec(
        id="job-unhealthy-test",
        run_id="run-1",
        name="unhealthy-test",
        command="python",
    )

    dead_node = ComputeNodeProfile(
        node_id="node-dead",
        tier=NodeProvisioningTier.STATIC,
        health_state=NodeHealthState.DEAD,
    )
    unhealthy_node = ComputeNodeProfile(
        node_id="node-unhealthy",
        tier=NodeProvisioningTier.STATIC,
        health_state=NodeHealthState.UNHEALTHY,
    )

    decision = engine.evaluate_placement(
        job=job,
        nodes=[dead_node, unhealthy_node],
        backlog_size=1,
    )
    sel_id = decision.selected_node_id
    assert sel_id is None
    assert decision.should_burst_ephemeral is False


def test_placement_routes_x86_64_to_gcp_e2_micro_and_handles_oci_spillover() -> None:
    """Verify x86_64 jobs route to GCP e2-micro and OCI exhaustion spills over."""
    engine = WarmCachePlacementEngine()

    oci_a1 = ComputeNodeProfile(
        node_id="oci-a1-node-01",
        arch="arm64",
        provider="oci",
        tier=NodeProvisioningTier.STATIC,
        capacity=NodeCapacity(
            node_id="oci-a1-node-01",
            total_cpus=4,
            available_cpus=4,
            total_ram_mb=24576,
            available_ram_mb=24576,
        ),
    )
    gcp_e2 = ComputeNodeProfile(
        node_id="gcp-e2-micro-01",
        arch="x86_64",
        provider="gcp",
        tier=NodeProvisioningTier.EPHEMERAL,
        capacity=NodeCapacity(
            node_id="gcp-e2-micro-01",
            total_cpus=2,
            available_cpus=2,
            total_ram_mb=1024,
            available_ram_mb=1024,
        ),
    )

    x86_job = JobSpec(
        id="job-x86",
        run_id="run-1",
        name="x86-wheel-build",
        command="pytest",
        requires_arch="x86_64",
    )
    dec_x86 = engine.evaluate_placement(job=x86_job, nodes=[oci_a1, gcp_e2])
    sel_x86 = dec_x86.selected_node_id
    assert sel_x86 == "gcp-e2-micro-01"

    arm_job = JobSpec(
        id="job-arm",
        run_id="run-1",
        name="arm-mutation",
        command="pytest",
        requires_arch="aarch64",
    )
    dec_arm = engine.evaluate_placement(job=arm_job, nodes=[oci_a1, gcp_e2])
    sel_arm = dec_arm.selected_node_id
    assert sel_arm == "oci-a1-node-01"

    generic_job = JobSpec(
        id="job-generic",
        run_id="run-1",
        name="spillover-job",
        command="pytest",
    )
    dec_spill = engine.evaluate_placement(
        job=generic_job,
        nodes=[oci_a1, gcp_e2],
        primary_pool_exhausted=True,
    )
    sel_spill = dec_spill.selected_node_id
    assert sel_spill == "gcp-e2-micro-01"
