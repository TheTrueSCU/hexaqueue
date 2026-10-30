"""Unit tests for AzureScaleSetAdapter."""

from unittest.mock import MagicMock

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleRequest
from hexaqueue_server.adapters.cloud.azure import AzureScaleSetAdapter


@pytest.mark.asyncio
async def test_azure_vmss_local_simulation() -> None:
    """Verify local pool registration, listing, and scaling."""
    adapter = AzureScaleSetAdapter()
    pool = InstancePoolState(
        pool_id="vmss-test-local",
        provider=CspProvider.AZURE,
        min_nodes=0,
        max_nodes=10,
        desired_nodes=1,
        current_nodes=1,
    )
    adapter.register_mock_pool(pool)

    pools = await adapter.list_pools()
    count = len(pools)
    assert count == 1

    state = await adapter.get_pool_state("vmss-test-local")
    nodes = state.current_nodes
    assert nodes == 1

    scale_res = await adapter.scale_pool(
        PoolScaleRequest(pool_id="vmss-test-local", target_nodes=3, reason="Test surge")
    )
    ok = scale_res.success
    assert ok is True
    target = scale_res.target_nodes
    assert target == 3

    updated = await adapter.get_pool_state("vmss-test-local")
    updated_nodes = updated.current_nodes
    assert updated_nodes == 3


@pytest.mark.asyncio
async def test_azure_vmss_with_client() -> None:
    """Verify Azure adapter interactions with injected compute client."""
    mock_client = MagicMock()
    mock_vmss = MagicMock()
    mock_sku = MagicMock()
    mock_sku.capacity = 2
    mock_vmss.sku = mock_sku
    mock_vmss.name = "vmss-prod"
    mock_client.virtual_machine_scale_sets.get.return_value = mock_vmss
    mock_client.virtual_machine_scale_sets.list.return_value = [mock_vmss]

    adapter = AzureScaleSetAdapter(
        azure_client=mock_client,
        resource_group="rg-prod",
    )
    pools = await adapter.list_pools()
    assert len(pools) == 1
    assert pools[0].pool_id == "vmss-prod"

    state = await adapter.get_pool_state("vmss-prod")
    p_id = state.pool_id
    assert p_id == "vmss-prod"
    curr = state.current_nodes
    assert curr == 2

    res = await adapter.scale_pool(
        PoolScaleRequest(pool_id="vmss-prod", target_nodes=6, reason="Burst")
    )
    ok = res.success
    assert ok is True
    mock_client.virtual_machine_scale_sets.begin_update.assert_called_once_with(
        resource_group_name="rg-prod",
        vm_scale_set_name="vmss-prod",
        parameters={"sku": {"capacity": 6}},
    )


@pytest.mark.asyncio
async def test_azure_vmss_not_found() -> None:
    """Verify error when VMSS is missing."""
    adapter = AzureScaleSetAdapter()
    with pytest.raises(HexaqueueError, match="not found"):
        await adapter.get_pool_state("nonexistent-vmss")
