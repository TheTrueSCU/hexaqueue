"""Tests for ResourceRequirements domain model."""

from hexaqueue_core.domain.resources import ResourceRequirements


def test_resource_requirements_defaults() -> None:
    """Verify ResourceRequirements default values."""
    req = ResourceRequirements()
    assert req.cpus == 1
    assert req.ram_mb == 1024
    assert req.gpus == 0
    assert req.gpu_model is None
    assert req.scratch_mb == 1024
    assert req.walltime_seconds == 3600
