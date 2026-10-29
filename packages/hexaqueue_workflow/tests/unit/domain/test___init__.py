"""Tests for domain package exports."""

import hexaqueue_workflow.domain as domain_pkg


def test_domain_exports() -> None:
    """Verify all expected domain entities are exported."""
    expected = [
        "ArtifactReference",
        "ArtifactStagingError",
        "BarrierPartition",
        "BarrierResolutionSummary",
        "BarrierState",
        "create_ephemeral_infra_saga",
        "DistributedWorkflowConfig",
        "HexaqueueWorkflowError",
        "InfraPlanSpec",
        "InfraProvisionResult",
        "JobExecutionFailedError",
        "StepMappingNotFoundError",
        "WorkflowStepJobMapping",
    ]
    exports = domain_pkg.__all__
    assert exports == sorted(expected, key=str.casefold)
