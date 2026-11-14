"""Dual-implementation oracle Hypothesis property tests for GCP e2-micro spillover.

Notes/Architectural Intent:
    Proves mathematical equivalence between GcpInstancePoolAdapter /
    WarmCachePlacementEngine and a naive reference oracle across arbitrary
    architecture constraints, Always-Free scaling bounds, and OCI capacity
    spillover states.
"""

from __future__ import annotations

import asyncio

from hypothesis import given, settings
from hypothesis import strategies as st

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.node import ComputeNodeProfile, NodeProvisioningTier
from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleRequest
from hexaqueue_core.ports.resources import NodeCapacity
from hexaqueue_server.adapters.cloud.gcp import GcpInstancePoolAdapter
from hexaqueue_server.domain.placement import WarmCachePlacementEngine


@given(
    target_nodes=st.integers(min_value=0, max_value=3),
    requires_arch=st.sampled_from([None, "arm64", "x86_64", "amd64", "aarch64"]),
    oci_exhausted=st.booleans(),
)
@settings(max_examples=30, deadline=None)
def test_gcp_e2_micro_spillover_matches_reference_oracle(
    target_nodes: int,
    requires_arch: str | None,
    oci_exhausted: bool,
) -> None:
    """Verify GcpInstancePoolAdapter and WarmCachePlacementEngine match oracle."""
    adapter = GcpInstancePoolAdapter(zone="us-central1-a")
    adapter.register_mock_pool(
        InstancePoolState(
            pool_id="hq-gcp-e2-micro",
            provider=CspProvider.GCP,
            min_nodes=0,
            max_nodes=1,
            desired_nodes=0,
            current_nodes=0,
        )
    )

    if target_nodes > 1:
        raised = False
        try:
            asyncio.run(
                adapter.scale_pool(
                    PoolScaleRequest(
                        pool_id="hq-gcp-e2-micro",
                        target_nodes=target_nodes,
                        reason="property-test",
                    )
                )
            )
        except HexaqueueError:
            raised = True
        assert raised is True
    else:
        res = asyncio.run(
            adapter.scale_pool(
                PoolScaleRequest(
                    pool_id="hq-gcp-e2-micro",
                    target_nodes=target_nodes,
                    reason="property-test",
                )
            )
        )
        ok = res.success
        assert ok is True
        target = res.target_nodes
        assert target == target_nodes

    engine = WarmCachePlacementEngine()
    oci_node = ComputeNodeProfile(
        node_id="oci-a1",
        arch="arm64",
        provider="oci",
        tier=NodeProvisioningTier.STATIC,
        capacity=NodeCapacity(
            node_id="oci-a1",
            total_cpus=4,
            available_cpus=4,
            total_ram_mb=24576,
            available_ram_mb=24576,
        ),
    )
    gcp_node = ComputeNodeProfile(
        node_id="gcp-e2",
        arch="x86_64",
        provider="gcp",
        tier=NodeProvisioningTier.EPHEMERAL,
        capacity=NodeCapacity(
            node_id="gcp-e2",
            total_cpus=2,
            available_cpus=2,
            total_ram_mb=1024,
            available_ram_mb=1024,
        ),
    )
    job = JobSpec(
        id="job-prop",
        run_id="run-prop",
        name="prop-job",
        command="pytest",
        requires_arch=requires_arch,
    )
    decision = engine.evaluate_placement(
        job=job,
        nodes=[oci_node, gcp_node],
        primary_pool_exhausted=oci_exhausted,
    )

    norm_arch = (
        "x86_64"
        if requires_arch == "amd64"
        else ("arm64" if requires_arch == "aarch64" else requires_arch)
    )
    if norm_arch == "arm64":
        expected = None if oci_exhausted else "oci-a1"
    elif norm_arch == "x86_64":
        expected = "gcp-e2"
    else:
        expected = "gcp-e2" if oci_exhausted else "oci-a1"

    selected = decision.selected_node_id
    assert selected == expected
