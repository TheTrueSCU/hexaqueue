"""Unit tests for container image assembler domain models."""

from hexaqueue_core.domain.container import ContainerRuntimeType
from hexaqueue_worker.domain.assembler import (
    AssembledImageResult,
    ImageArtifactMapping,
    ImageAssemblySpec,
)


def test_image_artifact_mapping_defaults() -> None:
    """Verify ImageArtifactMapping initialization and default properties."""
    mapping = ImageArtifactMapping(
        source_path="/host/bin/app",
        target_path="/usr/local/bin/app",
    )
    src = mapping.source_path
    tgt = mapping.target_path
    exe = mapping.executable
    assert src == "/host/bin/app"
    assert tgt == "/usr/local/bin/app"
    assert exe is False


def test_image_assembly_spec_digest_determinism() -> None:
    """Verify compute_cache_digest is deterministic and sensitive to changes."""
    spec1 = ImageAssemblySpec(
        base_image="alpine:3.20",
        runtime=ContainerRuntimeType.DOCKER,
        artifacts=[
            ImageArtifactMapping(
                source_path="/tmp/bin",
                target_path="/bin/run",
                executable=True,
            )
        ],
        install_commands=["apk add --no-cache curl"],
        env={"TEST_MODE": "1"},
        workdir="/workspace",
    )
    spec2 = ImageAssemblySpec(
        base_image="alpine:3.20",
        runtime=ContainerRuntimeType.DOCKER,
        artifacts=[
            ImageArtifactMapping(
                source_path="/tmp/bin",
                target_path="/bin/run",
                executable=True,
            )
        ],
        install_commands=["apk add --no-cache curl"],
        env={"TEST_MODE": "1"},
        workdir="/workspace",
    )
    d1 = spec1.compute_cache_digest()
    d2 = spec2.compute_cache_digest()
    assert d1 == d2
    tag1 = spec1.image_tag
    assert tag1.startswith("hq-cached:")

    # Permuted base image changes digest
    spec_diff = ImageAssemblySpec(
        base_image="ubuntu:24.04",
        runtime=spec1.runtime,
        artifacts=spec1.artifacts,
        install_commands=spec1.install_commands,
        env=spec1.env,
        workdir=spec1.workdir,
    )
    d_diff = spec_diff.compute_cache_digest()
    assert d_diff != d1


def test_image_assembly_spec_custom_tag() -> None:
    """Verify custom tag override bypasses content-addressable tag generation."""
    spec = ImageAssemblySpec(
        base_image="alpine:latest",
        custom_tag="custom-repo/image:v1.0",
    )
    tag = spec.image_tag
    assert tag == "custom-repo/image:v1.0"


def test_assembled_image_result() -> None:
    """Verify AssembledImageResult properties."""
    res = AssembledImageResult(
        image_tag="hq-cached:1234abcd",
        cached=True,
        build_time_seconds=0.05,
        log_output="Cached layer detected",
    )
    tag = res.image_tag
    cached = res.cached
    dur = res.build_time_seconds
    log = res.log_output
    assert tag == "hq-cached:1234abcd"
    assert cached is True
    assert dur == 0.05
    assert log == "Cached layer detected"
