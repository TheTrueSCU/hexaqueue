"""Domain models for container image assembly and content-addressable caching.

Notes/Architectural Intent:
    Represents declarative specifications for dynamic container image assembly
    layering base images with compiled binaries and test collaterals. Computes
    deterministic, content-addressable cache keys to eliminate redundant container builds.
"""

import hashlib

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.domain.container import ContainerRuntimeType


class ImageArtifactMapping(BaseModel):
    """Mapping of host artifact file or directory to in-container destination.

    Args:
        source_path: Host filesystem path to binary or collateral artifact.
        target_path: In-container absolute destination path.
        executable: Whether to ensure executable permissions (+x).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_path: str = Field(min_length=1, description="Host source path")
    target_path: str = Field(min_length=1, description="In-container destination path")
    executable: bool = Field(default=False, description="Set executable permission")


class ImageAssemblySpec(BaseModel):
    """Declarative specification for dynamic container image assembly.

    Args:
        base_image: Base container image tag or digest (e.g. 'alpine:latest' or Windows image).
        runtime: Preferred container runtime engine (Docker or Podman).
        artifacts: List of host-to-container artifact copy mappings.
        install_commands: Shell commands executed sequentially during image build.
        env: Environment variables baked into the container image.
        workdir: Working directory set inside the assembled image.
        tag_prefix: Prefix used for content-addressable cache tag (default 'hq-cached').
        custom_tag: Optional explicit tag override bypassing content-addressable hashing.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    base_image: str = Field(min_length=1, description="Base image identifier")
    runtime: ContainerRuntimeType = Field(
        default=ContainerRuntimeType.DOCKER, description="Container build runtime"
    )
    artifacts: list[ImageArtifactMapping] = Field(
        default_factory=list, description="Artifact copy mappings"
    )
    install_commands: list[str] = Field(
        default_factory=list, description="Build install commands"
    )
    env: dict[str, str] = Field(
        default_factory=dict, description="Image environment variables"
    )
    workdir: str = Field(default="/workspace", description="Default container workdir")
    tag_prefix: str = Field(default="hq-cached", description="Cache tag prefix")
    custom_tag: str | None = Field(default=None, description="Explicit tag override")

    def compute_cache_digest(self) -> str:
        """Compute deterministic SHA-256 cache digest of assembly specification.

        Returns:
            64-character hex digest representing base image, artifacts, commands, and environment.
        """
        hasher = hashlib.sha256()
        hasher.update(self.base_image.encode("utf-8"))
        hasher.update(str(self.runtime).encode("utf-8"))
        hasher.update(self.workdir.encode("utf-8"))
        for art in sorted(self.artifacts, key=lambda a: (a.source_path, a.target_path)):
            hasher.update(
                f"{art.source_path}->{art.target_path}:{art.executable}".encode()
            )
        for cmd in self.install_commands:
            hasher.update(cmd.encode("utf-8"))
        for k, v in sorted(self.env.items()):
            hasher.update(f"{k}={v}".encode())
        return hasher.hexdigest()

    @property
    def image_tag(self) -> str:
        """Return the effective image tag (custom_tag or content-addressable tag)."""
        if self.custom_tag:
            return self.custom_tag
        return f"{self.tag_prefix}:{self.compute_cache_digest()[:16]}"


class AssembledImageResult(BaseModel):
    """Result of a container image assembly operation.

    Args:
        image_tag: The assembled and tagged container image identifier.
        cached: True if image already existed in local container cache without rebuild.
        build_time_seconds: Elapsed duration of build or cache lookup.
        log_output: Optional stdout/stderr build logs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    image_tag: str = Field(description="Tagged container image identifier")
    cached: bool = Field(description="Whether image was served from local cache")
    build_time_seconds: float = Field(
        ge=0.0, description="Build or lookup duration in seconds"
    )
    log_output: str | None = Field(
        default=None, description="Container build output logs"
    )


__all__ = [
    "AssembledImageResult",
    "ImageArtifactMapping",
    "ImageAssemblySpec",
]
