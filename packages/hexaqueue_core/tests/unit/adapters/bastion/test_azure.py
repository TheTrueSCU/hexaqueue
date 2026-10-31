"""Unit tests for AzureBastionAdapter.

Notes/Architectural Intent:
    Validates Microsoft Azure Bastion keyless native SSH command generation,
    resource scoping, Entra ID auth type, and error validation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.adapters.bastion.azure import AzureBastionAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
)


@pytest.mark.anyio
async def test_azure_bastion_adapter_connection_command() -> None:
    """Verify AzureBastionAdapter renders valid az network bastion ssh command."""
    adapter = AzureBastionAdapter(
        bastion_name="bastion-hub",
        resource_group="rg-compute-prod",
        subscription="sub-123",
    )
    target_id = "/subscriptions/sub-123/resourceGroups/rg-compute-prod/providers/Microsoft.Compute/virtualMachines/vm-01"
    session = await adapter.generate_session_token(
        node_id="vm-01",
        operator_id="azure-admin@hexaqueue.org",
        duration_seconds=3600,
    )
    session.metadata["target_resource_id"] = target_id

    proto = session.protocol
    assert proto == BastionProtocolType.AZURE_BASTION

    cmd = await adapter.get_connection_command("vm-01", session)
    tokens = cmd.command
    assert tokens == [
        "az",
        "network",
        "bastion",
        "ssh",
        "--target-resource-id",
        target_id,
        "--auth-type",
        "AAD",
        "--name",
        "bastion-hub",
        "--resource-group",
        "rg-compute-prod",
        "--subscription",
        "sub-123",
    ]


@pytest.mark.anyio
async def test_azure_bastion_adapter_metadata_overrides() -> None:
    """Verify metadata overrides for bastion host and azure tenant ID."""
    adapter = AzureBastionAdapter()
    session = await adapter.generate_session_token(
        node_id="vm-02",
        operator_id="op-1",
    )
    session.metadata["bastion_name"] = "custom-bastion"
    session.metadata["resource_group"] = "custom-rg"
    session.metadata["azure_tenant"] = "tenant-uuid-42"
    session.metadata["auth_type"] = "password"

    cmd = await adapter.get_connection_command("vm-02", session)
    assert "--name" in cmd.command
    assert "custom-bastion" in cmd.command
    assert "--auth-type" in cmd.command
    assert "password" in cmd.command
    assert cmd.env.get("AZURE_TENANT_ID") == "tenant-uuid-42"


@pytest.mark.anyio
async def test_azure_bastion_adapter_session_validation_failures() -> None:
    """Verify error checking for invalid, inactive, or expired sessions."""
    adapter = AzureBastionAdapter()
    session = await adapter.generate_session_token("node-1", "op-1")

    with pytest.raises(ValueError, match="targets node 'node-1', not 'node-2'"):
        await adapter.get_connection_command("node-2", session)

    session.terminate()
    with pytest.raises(ValueError, match="is inactive"):
        await adapter.get_connection_command("node-1", session)

    session.is_active = True
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ValueError, match="has expired"):
        await adapter.get_connection_command("node-1", session)
