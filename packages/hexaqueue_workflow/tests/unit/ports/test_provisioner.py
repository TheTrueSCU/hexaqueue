"""Unit tests for InfrastructureProvisionerPort interface."""

import inspect
from pathlib import Path

import pytest

from hexaqueue_workflow.domain.provisioner import (
    InfraPlanSpec,
    InfraProvisionResult,
)
from hexaqueue_workflow.ports.provisioner import InfrastructureProvisionerPort


class DummyProvisioner(InfrastructureProvisionerPort):
    """Concrete dummy implementation of InfrastructureProvisionerPort."""

    async def provision(
        self, spec: InfraPlanSpec, workdir: Path
    ) -> InfraProvisionResult:
        return InfraProvisionResult(
            outputs={"db_host": "localhost"},
            success=True,
            duration_seconds=0.1,
        )

    async def destroy(self, spec: InfraPlanSpec, workdir: Path) -> InfraProvisionResult:
        return InfraProvisionResult(
            outputs={},
            success=True,
            duration_seconds=0.05,
        )

    async def plan(self, spec: InfraPlanSpec, workdir: Path) -> str:
        return "Plan: 1 to add, 0 to change, 0 to destroy."


@pytest.mark.asyncio
async def test_infrastructure_provisioner_port_contract(tmp_path: Path) -> None:
    """Verify concrete subclass can be instantiated and executed."""
    provisioner = DummyProvisioner()
    is_port = isinstance(provisioner, InfrastructureProvisionerPort)
    assert is_port is True

    spec = InfraPlanSpec(plan_path=str(tmp_path))
    res_prov = await provisioner.provision(spec, tmp_path)
    succ_prov = res_prov.success
    assert succ_prov is True
    assert res_prov.outputs["db_host"] == "localhost"

    plan_str = await provisioner.plan(spec, tmp_path)
    assert "Plan:" in plan_str

    res_dest = await provisioner.destroy(spec, tmp_path)
    succ_dest = res_dest.success
    assert succ_dest is True


def test_infrastructure_provisioner_port_is_abstract() -> None:
    """Verify that InfrastructureProvisionerPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(InfrastructureProvisionerPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        InfrastructureProvisionerPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_infrastructure_provisioner_port_abstract_methods() -> None:
    """Verify abstract methods on InfrastructureProvisionerPort."""
    expected = {"destroy", "plan", "provision"}
    abstracts = InfrastructureProvisionerPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
