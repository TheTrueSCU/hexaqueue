"""Unit tests for GcpManagedInstanceGroupAdapter."""

from unittest.mock import MagicMock

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleRequest
from hexaqueue_server.adapters.cloud.gcp import GcpManagedInstanceGroupAdapter


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
