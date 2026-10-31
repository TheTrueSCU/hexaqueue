"""Unit tests for AWSSSMAdapter.

Notes/Architectural Intent:
    Validates AWS SSM start-session command generation, zero-ingress security invariants,
    profile isolation, and parameter handling.
"""

from datetime import UTC, datetime, timedelta

import pytest

from hexaqueue_core.adapters.bastion.aws import AWSSSMAdapter
from hexaqueue_core.domain.bastion import (
    BastionProtocolType,
)


@pytest.mark.anyio
async def test_aws_ssm_adapter_connection_command() -> None:
    """Verify AWSSSMAdapter renders valid aws ssm start-session command."""
    adapter = AWSSSMAdapter(region_name="us-west-2", document_name="SSM-DefaultShell")
    session = await adapter.generate_session_token(
        node_id="i-0123456789abcdef0",
        operator_id="eng-1",
        duration_seconds=3600,
    )

    proto = session.protocol
    assert proto == BastionProtocolType.AWS_SSM

    cmd = await adapter.get_connection_command("i-0123456789abcdef0", session)
    tokens = cmd.command
    assert tokens == [
        "aws",
        "ssm",
        "start-session",
        "--target",
        "i-0123456789abcdef0",
        "--region",
        "us-west-2",
        "--document-name",
        "SSM-DefaultShell",
    ]


@pytest.mark.anyio
async def test_aws_ssm_adapter_metadata_overrides() -> None:
    """Verify instance_id and aws_profile metadata overrides."""
    adapter = AWSSSMAdapter()
    session = await adapter.generate_session_token(
        node_id="k8s-worker-pool-node-01",
        operator_id="eng-2",
        duration_seconds=1800,
    )
    session.metadata["instance_id"] = "i-custom99"
    session.metadata["aws_profile"] = "security-admin"
    session.metadata["region"] = "eu-central-1"

    cmd = await adapter.get_connection_command("k8s-worker-pool-node-01", session)
    assert "--target" in cmd.command
    assert "i-custom99" in cmd.command
    assert "--region" in cmd.command
    assert "eu-central-1" in cmd.command
    assert cmd.env.get("AWS_PROFILE") == "security-admin"


@pytest.mark.anyio
async def test_aws_ssm_adapter_session_validation_failures() -> None:
    """Verify command generation rejects inactive, expired, or mismatched sessions."""
    adapter = AWSSSMAdapter()
    session = await adapter.generate_session_token("node-1", "op-1")

    # Mismatched node_id
    with pytest.raises(ValueError, match="targets node 'node-1', not 'node-2'"):
        await adapter.get_connection_command("node-2", session)

    # Inactive session
    session.terminate()
    with pytest.raises(ValueError, match="is inactive"):
        await adapter.get_connection_command("node-1", session)

    # Expired session
    session.is_active = True
    session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(ValueError, match="has expired"):
        await adapter.get_connection_command("node-1", session)
