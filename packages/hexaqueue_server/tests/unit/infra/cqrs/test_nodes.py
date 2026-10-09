"""Unit tests for compute nodes, heartbeats, and bastion session CQRS handlers."""

from typing import Any

import pytest

from hexaqueue_core.domain.cqrs import (
    CreateBastionSessionCommand,
    GetNodesQuery,
    HeartbeatNodeCommand,
    ListComputeNodesQuery,
    RegisterNodeCommand,
)
from hexaqueue_core.domain.exceptions import PermissionDeniedError
from hexaqueue_core.domain.node import ComputeNodeProfile, NodeProvisioningTier


def test_bastion_elevation_enforcement(hermetic_cqrs_pipeline: tuple[Any, Any]) -> None:
    """Verify that node bastion SSH sessions strictly require administrative elevation."""
    _, pipeline = hermetic_cqrs_pipeline

    # Without elevation -> Rejected
    with pytest.raises(PermissionDeniedError) as exc_info:
        pipeline.execute(
            CreateBastionSessionCommand(
                node_id="worker-node-1",
                session_id="bastion-1",
                user_id="alice",
                elevate=False,
            )
        )
    assert "requires explicit administrative elevation" in str(exc_info.value)

    # With elevation -> Granted
    pty_info = pipeline.execute(
        CreateBastionSessionCommand(
            node_id="worker-node-1",
            session_id="bastion-1",
            user_id="alice",
            elevate=True,
        )
    )
    assert pty_info.session_id == "bastion-1"
    assert pty_info.job_id == "bastion-worker-node-1"
    assert pty_info.is_active is True


def test_node_registration_heartbeat_and_queries(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify node registration, heartbeat pulse, and node listing queries."""
    _, pipeline = hermetic_cqrs_pipeline

    # 1. Register node
    profile = ComputeNodeProfile(
        node_id="cqrs-worker-1",
        tier=NodeProvisioningTier.STATIC,
    )
    reg_res = pipeline.execute(RegisterNodeCommand(profile=profile))
    assert reg_res is None

    # 2. Heartbeat node
    hb_res = pipeline.execute(
        HeartbeatNodeCommand(
            worker_id="cqrs-worker-1",
            active_job_ids=["job-1"],
            cached_collateral_hashes=["hash-cqrs"],
        )
    )
    node_id = hb_res.node_id
    assert node_id == "cqrs-worker-1"
    assert "hash-cqrs" in hb_res.cached_collateral_hashes

    # 3. List compute nodes query
    nodes_report = pipeline.execute(ListComputeNodesQuery())
    tot_nodes = nodes_report.total_nodes
    assert tot_nodes >= 1

    # 4. Get nodes telemetry query
    nodes = pipeline.execute(GetNodesQuery())
    assert len(nodes) >= 1


def test_node_registration_and_heartbeat_authorization(
    hermetic_cqrs_pipeline: tuple[Any, Any],
) -> None:
    """Verify unauthorized registration and heartbeat spoofing are blocked."""
    _, pipeline = hermetic_cqrs_pipeline
    profile = ComputeNodeProfile(
        node_id="cqrs-worker-unauth",
        tier=NodeProvisioningTier.STATIC,
    )

    # Registration by unauthorized user without elevation -> rejected
    with pytest.raises(PermissionDeniedError) as exc_reg:
        pipeline.execute(
            RegisterNodeCommand(profile=profile, user_id="unauth-client", elevate=False)
        )
    assert "requires worker credentials or explicit administrative elevation" in str(
        exc_reg.value
    )

    # Heartbeat spoofing by unauthorized user without elevation -> rejected
    with pytest.raises(PermissionDeniedError) as exc_hb:
        pipeline.execute(
            HeartbeatNodeCommand(
                worker_id="cqrs-worker-1",
                active_job_ids=[],
                user_id="attacker",
                elevate=False,
            )
        )
    assert "requires worker credentials or explicit administrative elevation" in str(
        exc_hb.value
    )
