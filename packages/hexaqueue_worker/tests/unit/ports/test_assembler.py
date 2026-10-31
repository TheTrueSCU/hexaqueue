"""Tests for container image assembler port interface."""

import inspect

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


def test_container_image_assembler_port_is_abstract() -> None:
    """Verify that ContainerImageAssemblerPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(ContainerImageAssemblerPort)
    assert is_abs is True
    with pytest.raises(TypeError, match="Can't instantiate abstract class"):
        ContainerImageAssemblerPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]


def test_container_image_assembler_port_abstract_methods() -> None:
    """Verify abstract methods on ContainerImageAssemblerPort."""
    expected = {"assemble_image", "has_image", "remove_cached_image"}
    abstracts = ContainerImageAssemblerPort.__abstractmethods__
    diff = expected.difference(abstracts)
    assert len(diff) == 0
