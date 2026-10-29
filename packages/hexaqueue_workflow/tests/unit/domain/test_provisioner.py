"""Unit tests for infrastructure provisioner domain models and sagas."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from hexaqueue_workflow.domain.exceptions import HexaqueueWorkflowError
from hexaqueue_workflow.domain.provisioner import (
    InfraPlanSpec,
    InfraProvisionResult,
    create_ephemeral_infra_saga,
)


def test_infra_plan_spec_defaults() -> None:
    """Verify InfraPlanSpec defaults and validation."""
    spec = InfraPlanSpec(plan_path="/plans/database")
    path = spec.plan_path
    vars_dict = spec.variables
    env = spec.env
    timeout = spec.timeout_seconds
    assert path == "/plans/database"
    assert vars_dict == {}
    assert env == {}
    assert timeout == 900


def test_infra_provision_result_properties() -> None:
    """Verify InfraProvisionResult fields."""
    result = InfraProvisionResult(
        outputs={"endpoint": "10.0.0.1:5432", "user": "admin"},
        success=True,
        duration_seconds=12.5,
        state_file_path="/work/terraform.tfstate",
    )
    outs = result.outputs
    succ = result.success
    dur = result.duration_seconds
    state = result.state_file_path
    assert outs["endpoint"] == "10.0.0.1:5432"
    assert succ is True
    assert dur == 12.5
    assert state == "/work/terraform.tfstate"


@pytest.mark.asyncio
async def test_create_ephemeral_infra_saga_success(tmp_path: Path) -> None:
    """Verify forward action provisions and backward compensation destroys."""
    spec = InfraPlanSpec(plan_path=str(tmp_path / "plan"))
    mock_provisioner = MagicMock()
    mock_provisioner.provision = AsyncMock(
        return_value=InfraProvisionResult(
            outputs={"ip": "1.2.3.4"},
            success=True,
            duration_seconds=1.0,
        )
    )
    mock_provisioner.destroy = AsyncMock(
        return_value=InfraProvisionResult(
            outputs={},
            success=True,
            duration_seconds=0.5,
        )
    )

    action, compensation = create_ephemeral_infra_saga(spec, mock_provisioner, tmp_path)

    # 1. Forward action
    ctx = MagicMock()
    outputs = await action(ctx)
    assert outputs == {"ip": "1.2.3.4"}
    assert mock_provisioner.provision.called is True

    # 2. Backward compensation
    await compensation(ctx)
    assert mock_provisioner.destroy.called is True


@pytest.mark.asyncio
async def test_create_ephemeral_infra_saga_failure(tmp_path: Path) -> None:
    """Verify forward action raises HexaqueueWorkflowError if provisioning fails."""
    spec = InfraPlanSpec(plan_path=str(tmp_path / "plan"))
    mock_provisioner = MagicMock()
    mock_provisioner.provision = AsyncMock(
        return_value=InfraProvisionResult(
            outputs={},
            success=False,
            duration_seconds=0.2,
            error_message="Authentication failed",
        )
    )

    action, _ = create_ephemeral_infra_saga(spec, mock_provisioner, tmp_path)
    ctx = MagicMock()

    with pytest.raises(
        HexaqueueWorkflowError, match="Infrastructure provisioning failed"
    ):
        await action(ctx)
