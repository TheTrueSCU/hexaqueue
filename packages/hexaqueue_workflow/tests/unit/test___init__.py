"""Test hexaqueue_workflow package exports."""

import hexaqueue_workflow


def test_hexaqueue_workflow_package_exports() -> None:
    """Verify package exports match expected symbols."""
    expected = [
        "ArtifactReference",
        "ArtifactStagingError",
        "ArtifactStagingPort",
        "DistributedWorkflowConfig",
        "HexaqueueDistributedEngine",
        "HexaqueueWorkflowError",
        "JobExecutionFailedError",
        "StepMappingNotFoundError",
        "StoragePortArtifactStagingAdapter",
        "WorkflowStepJobMapping",
    ]
    exports = hexaqueue_workflow.__all__
    assert exports == sorted(expected)
