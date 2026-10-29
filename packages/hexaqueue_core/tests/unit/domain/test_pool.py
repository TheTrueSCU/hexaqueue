"""Unit tests for instance pool domain models and validations."""

import pytest
from pydantic import ValidationError

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.pool import (
    AutoscalerDecision,
    InstancePoolState,
    PoolScaleRequest,
    PoolScaleResult,
)


def test_instance_pool_state_valid() -> None:
    """Verify valid instance pool state attributes and defaults."""
    pool = InstancePoolState(
        pool_id="asg-win-workers",
        provider=CspProvider.AWS,
        min_nodes=0,
        max_nodes=10,
        desired_nodes=2,
        current_nodes=2,
        ready_nodes=2,
        spot_nodes=1,
        capability_tags=frozenset({"os:windows", "arch:x86_64"}),
        idle_drain_seconds=120,
    )
    p_id = pool.pool_id
    assert p_id == "asg-win-workers"
    prov = pool.provider
    assert prov == CspProvider.AWS
    desired = pool.desired_nodes
    assert desired == 2
    tags = pool.capability_tags
    assert "os:windows" in tags


def test_instance_pool_state_empty_id() -> None:
    """Verify empty pool_id raises validation error."""
    with pytest.raises(ValidationError, match="pool_id cannot be empty"):
        InstancePoolState(
            pool_id="   ",
            provider=CspProvider.GCP,
        )


def test_instance_pool_state_invalid_bounds() -> None:
    """Verify min_nodes > max_nodes raises validation error."""
    with pytest.raises(ValidationError, match="cannot exceed max_nodes"):
        InstancePoolState(
            pool_id="mig-gcp-pool",
            provider=CspProvider.GCP,
            min_nodes=10,
            max_nodes=2,
        )


def test_pool_scale_request_and_result() -> None:
    """Verify scale request and result data structures."""
    req = PoolScaleRequest(
        pool_id="vmss-azure-gpu",
        target_nodes=4,
        reason="Backlog queue surge",
    )
    target = req.target_nodes
    assert target == 4

    res = PoolScaleResult(
        pool_id="vmss-azure-gpu",
        previous_nodes=0,
        target_nodes=4,
        success=True,
        message="Scaled successfully",
    )
    ok = res.success
    assert ok is True
    msg = res.message
    assert msg == "Scaled successfully"


def test_pool_scale_request_empty_id() -> None:
    """Verify empty pool_id raises validation error in request."""
    with pytest.raises(ValidationError, match="pool_id cannot be empty"):
        PoolScaleRequest(pool_id="", target_nodes=1)


def test_autoscaler_decision() -> None:
    """Verify autoscaler decision model."""
    decision = AutoscalerDecision(
        pool_id="asg-win-workers",
        action="SCALE_UP",
        current_nodes=0,
        target_nodes=3,
        pending_jobs=6,
        reason="Demand queue depth reached 6",
    )
    act = decision.action
    assert act == "SCALE_UP"
    nodes = decision.target_nodes
    assert nodes == 3
