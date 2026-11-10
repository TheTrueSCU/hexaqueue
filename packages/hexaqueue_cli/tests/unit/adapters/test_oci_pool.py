"""Unit tests for OCI instance pool inspection adapter.

Notes/Architectural Intent:
    Hermetically verifies inspect_pool handling of missing SDK, successful queries,
    and exception branches using mock OCI clients.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

from hexaqueue_cli.adapters.oci_pool import DEFAULT_POOL_ID, inspect_pool


def test_inspect_pool_missing_sdk() -> None:
    """Verify inspect_pool gracefully fails when oci SDK is not installed."""
    with patch.dict(sys.modules, {"oci": None}):
        res = inspect_pool()
        assert res == 1


def test_inspect_pool_success() -> None:
    """Verify inspect_pool queries clients and returns 0."""
    mock_oci = MagicMock()
    mock_pool = MagicMock()
    mock_pool.display_name = "test-pool"
    mock_pool.id = DEFAULT_POOL_ID
    mock_pool.lifecycle_state = "RUNNING"
    mock_pool.size = 2
    mock_pool.compartment_id = "comp-1"

    mock_inst = MagicMock()
    mock_inst.id = "ocid1.instance.oc1.phx.test1"
    mock_inst.state = "Running"
    mock_inst.display_name = "worker-1"

    mock_mgmt = MagicMock()
    mock_mgmt.get_instance_pool.return_value.data = mock_pool
    mock_mgmt.list_instance_pool_instances.return_value.data = [mock_inst]

    mock_net = MagicMock()
    mock_vnic = MagicMock()
    mock_vnic.private_ip = "10.0.2.100"
    mock_net.get_vnic.return_value.data = mock_vnic

    mock_compute = MagicMock()
    mock_attachment = MagicMock()
    mock_attachment.vnic_id = "vnic-1"
    mock_compute.list_vnic_attachments.return_value.data = [mock_attachment]

    mock_oci.core.ComputeManagementClient.return_value = mock_mgmt
    mock_oci.core.VirtualNetworkClient.return_value = mock_net
    mock_oci.core.ComputeClient.return_value = mock_compute

    with patch.dict(sys.modules, {"oci": mock_oci}):
        res = inspect_pool(DEFAULT_POOL_ID)
        assert res == 0


def test_inspect_pool_fallback_to_config_file() -> None:
    """Verify fallback to oci.config.from_file when instance principals fail."""
    mock_oci = MagicMock()
    mock_oci.auth.signers.InstancePrincipalsSecurityTokenSigner.side_effect = Exception(
        "Not in OCI"
    )
    mock_oci.config.from_file.return_value = {
        "tenancy": "t-1",
        "user": "u-1",
        "fingerprint": "fp-1",
        "key_file": "/path/to/key",
    }
    mock_mgmt = MagicMock()
    mock_mgmt.get_instance_pool.return_value.data = MagicMock(
        compartment_id="comp-1", size=0
    )
    mock_mgmt.list_instance_pool_instances.return_value.data = []
    mock_oci.core.ComputeManagementClient.return_value = mock_mgmt

    with patch.dict(sys.modules, {"oci": mock_oci}):
        res = inspect_pool("test-pool")
        assert res == 0


def test_inspect_pool_vnic_exception() -> None:
    """Verify graceful handling when VNIC querying raises an exception."""
    mock_oci = MagicMock()
    mock_pool = MagicMock(compartment_id="comp-1", size=1)
    mock_inst = MagicMock(
        id="ocid1.instance.oc1.phx.test1", state="Running", display_name="worker-1"
    )
    mock_mgmt = MagicMock()
    mock_mgmt.get_instance_pool.return_value.data = mock_pool
    mock_mgmt.list_instance_pool_instances.return_value.data = [mock_inst]

    mock_compute = MagicMock()
    mock_compute.list_vnic_attachments.side_effect = Exception("VNIC network error")
    mock_oci.core.ComputeManagementClient.return_value = mock_mgmt
    mock_oci.core.ComputeClient.return_value = mock_compute

    with patch.dict(sys.modules, {"oci": mock_oci}):
        res = inspect_pool("test-pool")
        assert res == 0


def test_inspect_pool_general_exception() -> None:
    """Verify inspect_pool handles API failures and returns exit code 2."""
    mock_oci = MagicMock()
    mock_mgmt = MagicMock()
    mock_mgmt.get_instance_pool.side_effect = Exception("Pool not found")
    mock_oci.core.ComputeManagementClient.return_value = mock_mgmt

    with patch.dict(sys.modules, {"oci": mock_oci}):
        res = inspect_pool("test-pool")
        assert res == 2
