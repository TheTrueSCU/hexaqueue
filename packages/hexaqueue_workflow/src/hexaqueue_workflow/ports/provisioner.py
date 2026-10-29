"""Port interface for infrastructure-as-code provisioning and lifecycle management.

Notes/Architectural Intent:
    Defines abstract contract for initializing, applying, querying outputs, and
    destroying ephemeral infrastructure resources during workflow DAG execution.
"""

from abc import ABC, abstractmethod
from pathlib import Path

from hexaqueue_workflow.domain.provisioner import (
    InfraPlanSpec,
    InfraProvisionResult,
)


class InfrastructureProvisionerPort(ABC):
    """Abstract port interface for infrastructure provisioning engines."""

    @abstractmethod
    async def provision(
        self, spec: InfraPlanSpec, workdir: Path
    ) -> InfraProvisionResult:
        """Initialize and apply infrastructure resources, extracting output values.

        Args:
            spec: InfraPlanSpec defining plan source, variables, and timeout.
            workdir: Local directory serving as execution and state workspace.

        Returns:
            InfraProvisionResult containing captured outputs and status.

        Raises:
            HexaqueueWorkflowError: If provisioning fails critically.
        """

    @abstractmethod
    async def destroy(self, spec: InfraPlanSpec, workdir: Path) -> InfraProvisionResult:
        """Destroy previously provisioned infrastructure resources.

        Args:
            spec: InfraPlanSpec defining plan configuration and credentials.
            workdir: Directory containing execution state and backend config.

        Returns:
            InfraProvisionResult detailing destroy status and duration.
        """

    @abstractmethod
    async def plan(self, spec: InfraPlanSpec, workdir: Path) -> str:
        """Generate a dry-run execution plan string without applying changes.

        Args:
            spec: InfraPlanSpec defining plan configuration and variables.
            workdir: Directory containing plan files and state.

        Returns:
            Plan summary string or diff output.
        """


__all__ = [
    "InfrastructureProvisionerPort",
]
