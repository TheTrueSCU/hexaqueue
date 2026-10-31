"""Unit tests for GCPIAPAdapter.

Notes/Architectural Intent:
    Validates Google Cloud Identity-Aware Proxy (IAP) command rendering,
    zone/project scoping, and account environment isolation.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.adapters.bastion.gcp import GCPIAPAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
)


@pytest.mark.anyio
async def test_gcp_iap_adapter_connection_command() -> None:
    """Verify GCPIAPAdapter renders valid gcloud compute ssh --tunnel-through-iap command."""
    adapter = GCPIAPAdapter(project="hexaqueue-prod", zone="us-central1-a")
    session = await adapter.generate_session_token(
        node_id="gke-node-gpu-01",
        operator_id="sre-gcp@hexaqueue.org",
        duration_seconds=7200,
    )

    proto = session.protocol
    assert proto == BastionProtocolType.GCP_IAP

    cmd = await adapter.get_connection_command("gke-node-gpu-01", session)
    tokens = cmd.command
    assert tokens == [
        "gcloud",
        "compute",
        "ssh",
        "gke-node-gpu-01",
        "--tunnel-through-iap",
        "--project",
        "hexaqueue-prod",
        "--zone",
        "us-central1-a",
    ]


@pytest.mark.anyio
async def test_gcp_iap_adapter_metadata_overrides() -> None:
    """Verify instance_name, zone, project, and cloudsdk_account overrides."""
    adapter = GCPIAPAdapter()
    session = await adapter.generate_session_token(
        node_id="worker-01",
        operator_id="sre-1",
    )
    session.metadata["instance_name"] = "vm-worker-override"
    session.metadata["project"] = "custom-project"
    session.metadata["zone"] = "europe-west1-b"
    session.metadata["cloudsdk_account"] = "ops@corp.com"

    cmd = await adapter.get_connection_command("worker-01", session)
    assert "vm-worker-override" in cmd.command
    assert "--project" in cmd.command
    assert "custom-project" in cmd.command
    assert "--zone" in cmd.command
    assert "europe-west1-b" in cmd.command
    assert cmd.env.get("CLOUDSDK_CORE_ACCOUNT") == "ops@corp.com"


@pytest.mark.anyio
async def test_gcp_iap_adapter_session_validation_failures() -> None:
    """Verify error checking for invalid, inactive, or expired sessions."""
    adapter = GCPIAPAdapter()
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
