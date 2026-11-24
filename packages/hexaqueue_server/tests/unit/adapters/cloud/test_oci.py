"""Unit tests for OciInstancePoolAdapter."""

from types import SimpleNamespace
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

    with patch.dict("os.environ", {"HEXAQUEUE_OCI_MAX_POOL_SIZE": "0"}, clear=False):
        capped_state = await adapter.get_pool_state("ocid1.instancepool.oc1..pool1")
        assert capped_state.max_nodes == 0

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


@pytest.mark.asyncio
async def test_oci_instance_pool_starts_stopped_pool_on_scale_up() -> None:
    """Verify STOPPED OCI pool reports desired_nodes=0 and calls start_instance_pool on scale-up."""
    mock_client = MagicMock()
    mock_pool = MagicMock()
    mock_pool.size = 10
    mock_pool.lifecycle_state = "STOPPED"
    mock_pool.compartment_id = "ocid1.compartment.oc1..test"
    mock_pool.defined_tags = {}
    mock_client.get_instance_pool.return_value = MagicMock(data=mock_pool)
    mock_client.list_instance_pool_instances.return_value = MagicMock(data=[])

    adapter = OciInstancePoolAdapter(
        compute_management_client=mock_client,
        compartment_id="ocid1.compartment.oc1..test",
    )

    state = await adapter.get_pool_state("ocid1.instancepool.oc1..stopped")
    desired = state.desired_nodes
    current = state.current_nodes
    ready = state.ready_nodes
    assert desired == 0
    assert current == 0
    assert ready == 0

    # Scaling to 0 updates pool size without calling start_instance_pool
    zero_res = await adapter.scale_pool(
        PoolScaleRequest(
            pool_id="ocid1.instancepool.oc1..stopped",
            target_nodes=0,
        )
    )
    zero_ok = zero_res.success
    assert zero_ok is True
    mock_client.update_instance_pool.assert_called_once()
    mock_client.start_instance_pool.assert_not_called()

    # Scaling > 0 calls update_instance_pool AND start_instance_pool
    up_res = await adapter.scale_pool(
        PoolScaleRequest(
            pool_id="ocid1.instancepool.oc1..stopped",
            target_nodes=3,
        )
    )
    up_ok = up_res.success
    up_msg = up_res.message
    assert up_ok is True
    assert "started and resized" in up_msg
    mock_client.start_instance_pool.assert_called_once_with(
        instance_pool_id="ocid1.instancepool.oc1..stopped"
    )


def _make_capacity_probe_adapter(
    ad_statuses: dict[str, str | Exception],
) -> tuple[OciInstancePoolAdapter, MagicMock]:
    """Construct an OciInstancePoolAdapter with mock management & compute clients."""
    mgmt_client = MagicMock()
    mgmt_client.get_instance_pool.return_value = SimpleNamespace(
        data=SimpleNamespace(
            compartment_id="ocid1.compartment.oc1..test",
            instance_configuration_id="ocid1.instanceconfiguration.oc1..cfg",
            placement_configurations=[
                SimpleNamespace(availability_domain=ad) for ad in ad_statuses
            ],
        )
    )
    mgmt_client.get_instance_configuration.return_value = SimpleNamespace(
        data=SimpleNamespace(
            instance_details=SimpleNamespace(
                launch_details=SimpleNamespace(
                    shape="VM.Standard.E5.Flex",
                    shape_config=SimpleNamespace(ocpus=4.0, memory_in_gbs=16.0),
                )
            )
        )
    )

    compute_client = MagicMock()

    def _fake_report(details: object) -> SimpleNamespace:
        ad = (
            details["availability_domain"]
            if isinstance(details, dict)
            else getattr(details, "availability_domain", "")
        )
        verdict = ad_statuses[ad]
        if isinstance(verdict, Exception):
            raise verdict
        return SimpleNamespace(
            data=SimpleNamespace(
                shape_availabilities=[SimpleNamespace(availability_status=verdict)]
            )
        )

    compute_client.create_compute_capacity_report.side_effect = _fake_report
    adapter = OciInstancePoolAdapter(
        compute_management_client=mgmt_client,
        compartment_id="ocid1.compartment.oc1..test",
        compute_client=compute_client,
    )
    return adapter, compute_client


@pytest.mark.asyncio
async def test_oci_check_pool_capacity_available() -> None:
    """Verify check_pool_capacity returns True when any placement AD is AVAILABLE."""
    adapter, compute_client = _make_capacity_probe_adapter(
        {
            "uPhp:PHX-AD-1": "OUT_OF_HOST_CAPACITY",
            "uPhp:PHX-AD-2": "AVAILABLE",
            "uPhp:PHX-AD-3": "OUT_OF_HOST_CAPACITY",
        }
    )
    with patch(
        "hexaqueue_server.adapters.cloud.oci.optional_dependency", return_value=None
    ):
        has_cap = await adapter.check_pool_capacity("ocid1.instancepool.oc1..e5")
    assert has_cap is True
    call_count = compute_client.create_compute_capacity_report.call_count
    assert call_count == 2


@pytest.mark.asyncio
async def test_oci_check_pool_capacity_exhausted() -> None:
    """Verify check_pool_capacity returns False when all placement ADs are exhausted."""
    adapter, compute_client = _make_capacity_probe_adapter(
        {
            "uPhp:PHX-AD-1": "OUT_OF_HOST_CAPACITY",
            "uPhp:PHX-AD-2": "OUT_OF_HOST_CAPACITY",
        }
    )
    with patch(
        "hexaqueue_server.adapters.cloud.oci.optional_dependency", return_value=None
    ):
        has_cap = await adapter.check_pool_capacity("ocid1.instancepool.oc1..a1")
    assert has_cap is False
    call_count = compute_client.create_compute_capacity_report.call_count
    assert call_count == 2


@pytest.mark.asyncio
async def test_oci_check_pool_capacity_fails_open_on_error() -> None:
    """Verify check_pool_capacity fails open (returns True) on API permission errors."""
    adapter, _ = _make_capacity_probe_adapter(
        {"uPhp:PHX-AD-1": RuntimeError("404 NotAuthorizedOrNotFound")}
    )
    with patch(
        "hexaqueue_server.adapters.cloud.oci.optional_dependency", return_value=None
    ):
        has_cap = await adapter.check_pool_capacity("ocid1.instancepool.oc1..a1")
    assert has_cap is True
