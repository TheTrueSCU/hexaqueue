"""Unit tests for OciInstancePoolAdapter."""

from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.credentials import OciCredentialsConfig
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.pool import InstancePoolState, PoolScaleRequest
from hexaqueue_server.adapters.cloud.oci import OciInstancePoolAdapter


@pytest.mark.asyncio
async def test_oci_instance_pool_local_simulation() -> None:
    """Verify local OCI pool registration, listing, and scaling."""
    adapter = OciInstancePoolAdapter()
    pool = InstancePoolState(
        pool_id="ocid1.instancepool.oc1..test",
        provider=CspProvider.OCI,
        min_nodes=0,
        max_nodes=10,
        desired_nodes=2,
        current_nodes=2,
    )
    adapter.register_mock_pool(pool)

    pools = await adapter.list_pools()
    count = len(pools)
    assert count == 1

    state = await adapter.get_pool_state("ocid1.instancepool.oc1..test")
    nodes = state.current_nodes
    assert nodes == 2

    scale_res = await adapter.scale_pool(
        PoolScaleRequest(
            pool_id="ocid1.instancepool.oc1..test",
            target_nodes=4,
            reason="Ampere A1 scale-up",
        )
    )
    ok = scale_res.success
    assert ok is True
    target = scale_res.target_nodes
    assert target == 4

    updated_state = await adapter.get_pool_state("ocid1.instancepool.oc1..test")
    new_nodes = updated_state.current_nodes
    assert new_nodes == 4


@pytest.mark.asyncio
async def test_oci_instance_pool_with_client() -> None:
    """Verify OCI adapter interactions with injected ComputeManagementClient."""
    mock_client = MagicMock()
    mock_pool = MagicMock()
    mock_pool.size = 3
    mock_pool.defined_tags = {"Compute": {"Role": "Worker"}}
    mock_client.get_instance_pool.return_value = MagicMock(data=mock_pool)

    mock_inst1 = MagicMock(lifecycle_state="RUNNING")
    mock_inst2 = MagicMock(lifecycle_state="PROVISIONING")
    mock_inst3 = MagicMock(lifecycle_state="RUNNING")
    mock_client.list_instance_pool_instances.return_value = MagicMock(
        data=[mock_inst1, mock_inst2, mock_inst3]
    )

    adapter = OciInstancePoolAdapter(
        compute_management_client=mock_client,
        compartment_id="ocid1.compartment.oc1..test",
    )

    state = await adapter.get_pool_state("ocid1.instancepool.oc1..pool1")
    desired = state.desired_nodes
    assert desired == 3
    current = state.current_nodes
    assert current == 3
    ready = state.ready_nodes
    assert ready == 2

    # Scaling
    scale_res = await adapter.scale_pool(
        PoolScaleRequest(
            pool_id="ocid1.instancepool.oc1..pool1",
            target_nodes=5,
        )
    )
    success = scale_res.success
    assert success is True
    mock_client.update_instance_pool.assert_called_once()


@pytest.mark.asyncio
async def test_oci_instance_pool_dynamic_compartment() -> None:
    """Verify list_instance_pool_instances receives compartment_id from pool response."""
    mock_client = MagicMock()
    mock_pool = MagicMock()
    mock_pool.size = 1
    mock_pool.compartment_id = "ocid1.compartment.oc1..from-pool"
    mock_pool.defined_tags = {}
    mock_client.get_instance_pool.return_value = MagicMock(data=mock_pool)
    mock_client.list_instance_pool_instances.return_value = MagicMock(data=[])

    adapter = OciInstancePoolAdapter(
        compute_management_client=mock_client,
        compartment_id="ocid1.compartment.oc1..default",
    )
    res = await adapter.get_pool_state("ocid1.instancepool.oc1..pool1")
    count = res.desired_nodes
    assert count == 1
    mock_client.list_instance_pool_instances.assert_called_once_with(
        compartment_id="ocid1.compartment.oc1..from-pool",
        instance_pool_id="ocid1.instancepool.oc1..pool1",
    )


@pytest.mark.asyncio
async def test_oci_instance_pool_errors() -> None:
    """Verify error propagation when OCI instance pool is not found or API fails."""
    adapter = OciInstancePoolAdapter()
    with pytest.raises(HexaqueueError, match="not found in registered pools"):
        await adapter.get_pool_state("nonexistent-pool")

    mock_client = MagicMock()
    mock_client.get_instance_pool.side_effect = RuntimeError("OCI 404 Not Found")
    err_adapter = OciInstancePoolAdapter(compute_management_client=mock_client)
    with pytest.raises(HexaqueueError, match="Failed to get OCI instance pool"):
        await err_adapter.get_pool_state("ocid1.instancepool.oc1..fail")


def test_oci_from_credentials_factory() -> None:
    """Verify from_credentials factory behavior with different configurations."""
    # 1. Unconfigured credentials -> runs in mock mode
    adapter_unconf = OciInstancePoolAdapter.from_credentials()
    has_client = adapter_unconf._client is not None
    assert has_client is False

    # 2. Configured credentials with mock oci module
    creds = OciCredentialsConfig(
        tenancy_ocid="ocid1.tenancy.oc1..aaaa",
        user_ocid="ocid1.user.oc1..bbbb",
        fingerprint="aa:bb:cc:dd",
        key_content=SecretStr("MOCK_KEY_CONTENT"),
        region="us-ashburn-1",
    )

    mock_oci = MagicMock()
    with patch(
        "hexaqueue_server.adapters.cloud.oci.optional_dependency",
        return_value=mock_oci,
    ):
        adapter_conf = OciInstancePoolAdapter.from_credentials(creds)
        client_present = adapter_conf._client is not None
        assert client_present is True
        mock_oci.core.ComputeManagementClient.assert_called_once()
