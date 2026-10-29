"""Tests for container image assembler port interface."""

import pytest

from hexaqueue_worker.domain.assembler import (
    AssembledImageResult,
    ImageAssemblySpec,
)
from hexaqueue_worker.ports.assembler import ContainerImageAssemblerPort


class DummyImageAssembler(ContainerImageAssemblerPort):
    """Concrete implementation of ContainerImageAssemblerPort for interface testing."""

    async def assemble_image(self, spec: ImageAssemblySpec) -> AssembledImageResult:
        return AssembledImageResult(
            image_tag=spec.image_tag,
            cached=True,
            build_time_seconds=0.1,
        )

    async def has_image(self, image_tag: str, runtime: str = "docker") -> bool:
        return True

    async def remove_cached_image(
        self, image_tag: str, runtime: str = "docker"
    ) -> None:
        pass


@pytest.mark.asyncio
async def test_container_image_assembler_port_instantiation() -> None:
    """Verify concrete subclass can be instantiated and executed."""
    assembler = DummyImageAssembler()
    is_port = isinstance(assembler, ContainerImageAssemblerPort)
    assert is_port is True

    spec = ImageAssemblySpec(base_image="alpine:latest")
    res = await assembler.assemble_image(spec)
    cached = res.cached
    assert cached is True

    has_img = await assembler.has_image("alpine:latest")
    assert has_img is True
