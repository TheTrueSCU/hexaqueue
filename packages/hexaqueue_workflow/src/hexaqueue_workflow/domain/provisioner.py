"""Domain models for infrastructure provisioning and automated saga compensations.

Notes/Architectural Intent:
    Encapsulates declarative specifications for ephemeral cloud/testbed infrastructure
    plans (Terraform, OpenTofu). Enables pairing forward infrastructure creation with
    guaranteed backward teardown compensations in distributed saga workflows.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_workflow.domain.exceptions import HexaqueueWorkflowError


class InfraPlanSpec(BaseModel):
    """Specification of an infrastructure plan for provisioning.

    Args:
        plan_path: Path to the directory containing .tf or .tofu files.
        variables: Key-value map of Terraform/OpenTofu input variables.
        env: Environment variables (e.g. cloud credentials) injected into execution.
        backend_config: Key-value map of backend initialization overrides.
        timeout_seconds: Timeout for provisioning/destroying infrastructure in seconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_path: str = Field(min_length=1, description="Path to plan directory")
    variables: dict[str, Any] = Field(
        default_factory=dict, description="Input variables"
    )
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    backend_config: dict[str, str] = Field(
        default_factory=dict, description="Backend config parameters"
    )
    timeout_seconds: int = Field(
        default=900, description="Provisioning timeout in seconds"
    )


class InfraProvisionResult(BaseModel):
    """Result of an infrastructure provisioning or teardown operation.

    Args:
        outputs: Structured key-value outputs extracted from the applied plan.
        success: Whether the operation completed successfully.
        duration_seconds: Wall-clock duration of the operation in seconds.
        error_message: Optional error message on failure.
        state_file_path: Optional path to the generated state file.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    outputs: dict[str, Any] = Field(
        default_factory=dict, description="Applied plan outputs"
    )
    success: bool = Field(description="Operation success status")
    duration_seconds: float = Field(ge=0.0, description="Operation duration in seconds")
    error_message: str | None = Field(
        default=None, description="Detailed error description"
    )
    state_file_path: str | None = Field(
        default=None, description="Path to output state file"
    )


def create_ephemeral_infra_saga(
    spec: InfraPlanSpec,
    provisioner: Any,
    workdir: Path | str,
) -> tuple[Callable[..., Any], Callable[..., Any]]:
    """Construct forward action and compensation callbacks for ephemeral infrastructure.

    Args:
        spec: InfraPlanSpec describing infrastructure to create and destroy.
        provisioner: Instance implementing InfrastructureProvisionerPort.
        workdir: Working directory hosting plan execution context and state.

    Returns:
        Tuple of (action_coroutine, compensation_coroutine) suitable for StepDefinition.
    """
    target_dir = Path(workdir)

    async def forward_action(ctx: Any) -> dict[str, Any]:
        """Apply infrastructure and publish outputs to step context."""
        result: InfraProvisionResult = await provisioner.provision(spec, target_dir)
        if not result.success:
            msg = f"Infrastructure provisioning failed: {result.error_message}"
            raise HexaqueueWorkflowError(msg)
        return result.outputs

    async def backward_compensation(ctx: Any) -> None:
        """Destroy ephemeral infrastructure on workflow failure, abort, or teardown."""
        await provisioner.destroy(spec, target_dir)

    return forward_action, backward_compensation


__all__ = [
    "create_ephemeral_infra_saga",
    "InfraPlanSpec",
    "InfraProvisionResult",
]
