"""Unit tests for OpenTofuProvisionerAdapter (Issue #104)."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hexaqueue_workflow.adapters.opentofu import OpenTofuProvisionerAdapter
from hexaqueue_workflow.domain.exceptions import HexaqueueWorkflowError
from hexaqueue_workflow.domain.provisioner import InfraPlanSpec


def test_prepare_workspace_with_variables_and_files(tmp_path: Path) -> None:
    """Verify workspace copying and terraform.tfvars.json rendering."""
    adapter = OpenTofuProvisionerAdapter()
    plan_dir = tmp_path / "plan_src"
    plan_dir.mkdir()
    (plan_dir / "main.tf").write_text('output "val" { value = 1 }', encoding="utf-8")

    workdir = tmp_path / "workspace"
    spec = InfraPlanSpec(
        plan_path=str(plan_dir),
        variables={"region": "us-east-1", "count": 2},
    )

    adapter._prepare_workspace(spec, workdir)

    assert (workdir / "main.tf").exists() is True
    vars_file = workdir / "terraform.tfvars.json"
    assert vars_file.exists() is True
    parsed = json.loads(vars_file.read_text(encoding="utf-8"))
    assert parsed == {"region": "us-east-1", "count": 2}


@pytest.mark.asyncio
async def test_provision_success(tmp_path: Path) -> None:
    """Verify provision runs init, apply, and extracts json outputs."""
    adapter = OpenTofuProvisionerAdapter()
    spec = InfraPlanSpec(
        plan_path=str(tmp_path),
        backend_config={"bucket": "my-bucket"},
    )

    mock_proc_init = MagicMock()
    mock_proc_init.returncode = 0
    mock_proc_init.communicate = AsyncMock(return_value=(b"Initialized", b""))

    mock_proc_apply = MagicMock()
    mock_proc_apply.returncode = 0
    mock_proc_apply.communicate = AsyncMock(return_value=(b"Apply complete!", b""))

    mock_proc_output = MagicMock()
    mock_proc_output.returncode = 0
    raw_outputs = json.dumps({"db_ip": {"value": "10.0.0.5"}}).encode("utf-8")
    mock_proc_output.communicate = AsyncMock(return_value=(raw_outputs, b""))

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=[mock_proc_init, mock_proc_apply, mock_proc_output],
    ):
        result = await adapter.provision(spec, tmp_path)

    succ = result.success
    assert succ is True
    assert result.outputs == {"db_ip": "10.0.0.5"}


@pytest.mark.asyncio
async def test_provision_init_failure(tmp_path: Path) -> None:
    """Verify init failure returns success=False without running apply."""
    adapter = OpenTofuProvisionerAdapter()
    spec = InfraPlanSpec(plan_path=str(tmp_path))

    mock_proc_init = MagicMock()
    mock_proc_init.returncode = 1
    mock_proc_init.communicate = AsyncMock(
        return_value=(b"", b"Error loading backend config")
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_init):
        result = await adapter.provision(spec, tmp_path)

    succ = result.success
    assert succ is False
    assert "Init failed" in str(result.error_message)


@pytest.mark.asyncio
async def test_provision_apply_failure(tmp_path: Path) -> None:
    """Verify apply failure returns success=False."""
    adapter = OpenTofuProvisionerAdapter()
    spec = InfraPlanSpec(plan_path=str(tmp_path))

    mock_proc_init = MagicMock()
    mock_proc_init.returncode = 0
    mock_proc_init.communicate = AsyncMock(return_value=(b"OK", b""))

    mock_proc_apply = MagicMock()
    mock_proc_apply.returncode = 1
    mock_proc_apply.communicate = AsyncMock(
        return_value=(b"", b"ResourceQuotaExceeded")
    )

    with patch(
        "asyncio.create_subprocess_exec",
        side_effect=[mock_proc_init, mock_proc_apply],
    ):
        result = await adapter.provision(spec, tmp_path)

    succ = result.success
    assert succ is False
    assert "Apply failed" in str(result.error_message)


@pytest.mark.asyncio
async def test_destroy_success(tmp_path: Path) -> None:
    """Verify destroy runs destroy command."""
    adapter = OpenTofuProvisionerAdapter()
    spec = InfraPlanSpec(plan_path=str(tmp_path))

    mock_proc_dest = MagicMock()
    mock_proc_dest.returncode = 0
    mock_proc_dest.communicate = AsyncMock(return_value=(b"Destroy complete!", b""))

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_dest):
        result = await adapter.destroy(spec, tmp_path)

    succ = result.success
    assert succ is True


@pytest.mark.asyncio
async def test_destroy_failure(tmp_path: Path) -> None:
    """Verify destroy failure returns success=False with error message."""
    adapter = OpenTofuProvisionerAdapter()
    spec = InfraPlanSpec(plan_path=str(tmp_path))

    mock_proc_dest = MagicMock()
    mock_proc_dest.returncode = 2
    mock_proc_dest.communicate = AsyncMock(
        return_value=(b"", b"Failed to release elastic IP")
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_dest):
        result = await adapter.destroy(spec, tmp_path)

    succ = result.success
    assert succ is False
    assert "Destroy failed" in str(result.error_message)


@pytest.mark.asyncio
async def test_plan_dry_run_success(tmp_path: Path) -> None:
    """Verify plan returns stdout plan diff text."""
    adapter = OpenTofuProvisionerAdapter()
    spec = InfraPlanSpec(plan_path=str(tmp_path))

    mock_proc_plan = MagicMock()
    mock_proc_plan.returncode = 0
    mock_proc_plan.communicate = AsyncMock(
        return_value=(b"1 to add, 0 to destroy", b"")
    )

    with patch("asyncio.create_subprocess_exec", return_value=mock_proc_plan):
        plan_out = await adapter.plan(spec, tmp_path)

    assert "1 to add, 0 to destroy" in plan_out


@pytest.mark.asyncio
async def test_plan_dry_run_failure(tmp_path: Path) -> None:
    """Verify plan failure raises HexaqueueWorkflowError."""
    adapter = OpenTofuProvisionerAdapter()
    spec = InfraPlanSpec(plan_path=str(tmp_path))

    mock_proc_plan = MagicMock()
    mock_proc_plan.returncode = 1
    mock_proc_plan.communicate = AsyncMock(
        return_value=(b"", b"Syntax error in main.tf")
    )

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc_plan),
        pytest.raises(HexaqueueWorkflowError, match="Plan dry-run failed"),
    ):
        await adapter.plan(spec, tmp_path)


@pytest.mark.asyncio
async def test_command_timeout(tmp_path: Path) -> None:
    """Verify command timeout raises HexaqueueWorkflowError."""
    adapter = OpenTofuProvisionerAdapter(default_timeout_seconds=1)
    spec = InfraPlanSpec(plan_path=str(tmp_path), timeout_seconds=1)

    mock_proc = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError())
    mock_proc.kill = MagicMock()

    with (
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
        pytest.raises(HexaqueueWorkflowError, match="timed out"),
    ):
        await adapter.provision(spec, tmp_path)
