"""Unit tests for container execution domain models (Issue #30)."""

import pytest

from hexaqueue_core.domain.container import (
    ContainerMount,
    ContainerRuntimeType,
    ContainerSpec,
)
from hexaqueue_core.domain.job import JobSpec


def test_container_mount_validation() -> None:
    """Verify ContainerMount attributes and validation invariants."""
    mount = ContainerMount(
        source="/host/data", target="/container/data", read_only=True
    )
    src = mount.source
    assert src == "/host/data"
    tgt = mount.target
    assert tgt == "/container/data"
    ro = mount.read_only
    assert ro is True

    with pytest.raises(ValueError):
        ContainerMount(source="", target="/container/data")

    with pytest.raises(ValueError, match="source path cannot be empty"):
        ContainerMount(source="   ", target="/container/data")

    with pytest.raises(ValueError):
        ContainerMount(source="/host/data", target="")

    with pytest.raises(ValueError, match="target path cannot be empty"):
        ContainerMount(source="/host/data", target="   ")


def test_container_spec_defaults_and_validation() -> None:
    """Verify ContainerSpec defaults and validation."""
    spec = ContainerSpec(image="docker.io/library/alpine:latest")
    img = spec.image
    assert img == "docker.io/library/alpine:latest"
    wdir = spec.workdir
    assert wdir == "/workspace"
    ro = spec.read_only_rootfs
    assert ro is False
    gpu = spec.gpu_enabled
    assert gpu is False
    priv = spec.privileged
    assert priv is False
    run_type = spec.runtime
    assert run_type is None

    with pytest.raises(ValueError):
        ContainerSpec(image="")

    with pytest.raises(ValueError, match="image cannot be empty"):
        ContainerSpec(image="   ")


def test_container_runtime_type_enum() -> None:
    """Verify ContainerRuntimeType enum values."""
    podman_val = str(ContainerRuntimeType.PODMAN)
    assert podman_val == "podman"
    apptainer_val = str(ContainerRuntimeType.APPTAINER)
    assert apptainer_val == "apptainer"


def test_job_spec_with_container() -> None:
    """Verify JobSpec integration with ContainerSpec."""
    c_spec = ContainerSpec(
        image="python:3.13-slim",
        runtime=ContainerRuntimeType.PODMAN,
        gpu_enabled=True,
        mounts=[ContainerMount(source="/tmp/scratch", target="/workspace")],
    )
    job = JobSpec(
        id="job-container-001",
        run_id="run-1",
        name="container-task",
        command="python -V",
        container=c_spec,
    )
    has_container = job.container is not None
    assert has_container is True
    job_c_img = job.container.image if job.container else None
    assert job_c_img == "python:3.13-slim"
    job_c_gpu = job.container.gpu_enabled if job.container else False
    assert job_c_gpu is True
