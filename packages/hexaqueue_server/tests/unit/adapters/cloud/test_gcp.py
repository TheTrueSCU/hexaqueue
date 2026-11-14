"""Unit tests for GcpManagedInstanceGroupAdapter."""

from unittest.mock import MagicMock

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleRequest
from hexaqueue_server.adapters.cloud.gcp import (
    GcpInstancePoolAdapter,
    GcpManagedInstanceGroupAdapter,
)


@pytest.mark.asyncio
async def test_gcp_mig_local_simulation() -> None:
    """Verify local pool registration, listing, and scaling."""
    adapter = GcpManagedInstanceGroupAdapter()
    pool = InstancePoolState(
        pool_id="mig-test-local",
        provider=CspProvider.GCP,
        min_nodes=0,
        max_nodes=10,
        desired_nodes=2,
        current_nodes=2,
    )
    adapter.register_mock_pool(pool)

    pools = await adapter.list_pools()
    count = len(pools)
    assert count == 1

    state = await adapter.get_pool_state("mig-test-local")
    nodes = state.current_nodes
    assert nodes == 2

    scale_res = await adapter.scale_pool(
        PoolScaleRequest(pool_id="mig-test-local", target_nodes=6, reason="Batch load")
    )
    ok = scale_res.success
    assert ok is True
    target = scale_res.target_nodes
    assert target == 6

    updated = await adapter.get_pool_state("mig-test-local")
    updated_nodes = updated.current_nodes
    assert updated_nodes == 6


@pytest.mark.asyncio
async def test_gcp_mig_with_client() -> None:
    """Verify GCP adapter interactions with injected compute client."""
    mock_client = MagicMock()
    mock_mig = MagicMock()
    mock_mig.target_size = 4
    mock_mig.name = "mig-prod"
    mock_client.get.return_value = mock_mig
    mock_client.list.return_value = [mock_mig]

    adapter = GcpManagedInstanceGroupAdapter(
        compute_client=mock_client,
        project="my-proj",
        zone="europe-west1-b",
    )
    pools = await adapter.list_pools()
    assert len(pools) == 1
    assert pools[0].pool_id == "mig-prod"

    state = await adapter.get_pool_state("mig-prod")
    p_id = state.pool_id
    assert p_id == "mig-prod"
    curr = state.current_nodes
    assert curr == 4

    res = await adapter.scale_pool(
        PoolScaleRequest(pool_id="mig-prod", target_nodes=8, reason="Scale out")
    )
    ok = res.success
    assert ok is True
    mock_client.resize.assert_called_once_with(
        project="my-proj",
        zone="europe-west1-b",
        instance_group_manager="mig-prod",
        size=8,
    )


@pytest.mark.asyncio
async def test_gcp_mig_not_found() -> None:
    """Verify error when MIG is missing."""
    adapter = GcpManagedInstanceGroupAdapter()
    with pytest.raises(HexaqueueError, match="not found"):
        await adapter.get_pool_state("nonexistent-mig")


@pytest.mark.asyncio
async def test_gcp_instance_pool_local_simulation_and_bounds() -> None:
    """Verify GcpInstancePoolAdapter Always-Free e2-micro lifecycle and max=1 bound."""
    adapter = GcpInstancePoolAdapter(zone="us-central1-a")
    pool = InstancePoolState(
        pool_id="hq-gcp-e2-micro",
        provider=CspProvider.GCP,
        min_nodes=0,
        max_nodes=1,
        desired_nodes=0,
        current_nodes=0,
    )
    adapter.register_mock_pool(pool)

    listed = await adapter.list_pools()
    list_len = len(listed)
    assert list_len == 1

    up_res = await adapter.scale_pool(
        PoolScaleRequest(
            pool_id="hq-gcp-e2-micro",
            target_nodes=1,
            reason="x86_64 spillover",
        )
    )
    up_ok = up_res.success
    assert up_ok is True
    up_target = up_res.target_nodes
    assert up_target == 1

    state_up = await adapter.get_pool_state("hq-gcp-e2-micro")
    curr_up = state_up.current_nodes
    assert curr_up == 1

    with pytest.raises(HexaqueueError, match="Always-Free"):
        await adapter.scale_pool(
            PoolScaleRequest(
                pool_id="hq-gcp-e2-micro",
                target_nodes=2,
                reason="Exceed Always-Free limit",
            )
        )


@pytest.mark.asyncio
async def test_gcp_instance_pool_with_client_start_stop() -> None:
    """Verify GcpInstancePoolAdapter delegates start/stop to Compute InstancesClient."""
    mock_client = MagicMock()
    stopped_inst = MagicMock()
    stopped_inst.name = "hq-gcp-e2-micro"
    stopped_inst.status = "TERMINATED"
    mock_client.get.return_value = stopped_inst
    mock_client.list.return_value = [stopped_inst]

    adapter = GcpInstancePoolAdapter(
        instances_client=mock_client,
        project="hexaqueue-free",
        zone="us-west1-b",
    )
    pools = await adapter.list_pools()
    pool_count = len(pools)
    assert pool_count == 1
    assert pools[0].current_nodes == 0

    start_res = await adapter.scale_pool(
        PoolScaleRequest(
            pool_id="hq-gcp-e2-micro",
            target_nodes=1,
            reason="Start subordinate e2-micro",
        )
    )
    assert start_res.success is True
    mock_client.start.assert_called_once_with(
        project="hexaqueue-free",
        zone="us-west1-b",
        instance="hq-gcp-e2-micro",
    )

    running_inst = MagicMock()
    running_inst.name = "hq-gcp-e2-micro"
    running_inst.status = "RUNNING"
    mock_client.get.return_value = running_inst

    stop_res = await adapter.scale_pool(
        PoolScaleRequest(
            pool_id="hq-gcp-e2-micro",
            target_nodes=0,
            reason="Scale to zero",
        )
    )
    assert stop_res.success is True
    mock_client.stop.assert_called_once_with(
        project="hexaqueue-free",
        zone="us-west1-b",
        instance="hq-gcp-e2-micro",
    )
