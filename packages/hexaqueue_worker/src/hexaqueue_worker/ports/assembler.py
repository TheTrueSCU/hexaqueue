"""Port interface for dynamic container image assembly and caching.

Notes/Architectural Intent:
    Defines abstract contract for layering base images with compiled binaries
    and test collaterals, querying local container image cache, and purging
    ephemeral test images.
"""

from abc import ABC, abstractmethod

from hexaqueue_worker.domain.assembler import (
    AssembledImageResult,
    ImageAssemblySpec,
)


class ContainerImageAssemblerPort(ABC):
    """Abstract port interface for container image assembly and caching."""

    @abstractmethod
    async def assemble_image(self, spec: ImageAssemblySpec) -> AssembledImageResult:
        """Assemble a container image with layered artifacts and install commands.

        Args:
            spec: ImageAssemblySpec defining base image, artifacts, and build steps.

        Returns:
            AssembledImageResult with final image tag and cache status.

        Raises:
            HexaqueueError: If container build fails.
        """

    @abstractmethod
    async def has_image(self, image_tag: str, runtime: str = "docker") -> bool:
        """Check if container image exists in local container engine image cache.

        Args:
            image_tag: Image tag or digest to verify.
            runtime: Runtime executable name ('docker' or 'podman').

        Returns:
            True if image exists locally, False otherwise.
        """

    @abstractmethod
    async def remove_cached_image(
        self, image_tag: str, runtime: str = "docker"
    ) -> None:
        """Remove a cached container image from local storage.

        Args:
            image_tag: Image tag or digest to remove.
            runtime: Runtime executable name ('docker' or 'podman').
        """


__all__ = [
    "ContainerImageAssemblerPort",
]
