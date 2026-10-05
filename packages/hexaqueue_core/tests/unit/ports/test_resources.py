"""Tests for ComputeResourcePort and NodeCapacity."""

import pytest

from hexaqueue_core.ports.resources import ComputeResourcePort, NodeCapacity


def test_compute_resource_port_is_abstract() -> None:
    """Verify ComputeResourcePort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ComputeResourcePort()  # type: ignore[abstract]


def test_node_capacity_model() -> None:
    """Verify NodeCapacity model and invariants."""
    cap = NodeCapacity(
        node_id="node-1",
        total_cpus=8,
        total_ram_mb=16384,
        available_cpus=4,
        available_ram_mb=8192,
    )
    assert cap.node_id == "node-1"
    assert cap.total_cpus == 8
    assert cap.available_cpus == 4

    with pytest.raises(ValueError, match="node_id cannot be empty"):
        NodeCapacity(
            node_id="  ",
            total_cpus=8,
            total_ram_mb=16384,
            available_cpus=4,
            available_ram_mb=8192,
        )

    with pytest.raises(ValueError, match="available_cpus.*exceeds total_cpus"):
        NodeCapacity(
            node_id="node-1",
            total_cpus=4,
            total_ram_mb=16384,
            available_cpus=8,
            available_ram_mb=8192,
        )

    with pytest.raises(ValueError, match="available_ram_mb.*exceeds total_ram_mb"):
        NodeCapacity(
            node_id="node-1",
            total_cpus=8,
            total_ram_mb=4096,
            available_cpus=4,
            available_ram_mb=8192,
        )

    with pytest.raises(ValueError, match="available_gpus.*exceeds total_gpus"):
        NodeCapacity(
            node_id="node-1",
            total_cpus=8,
            total_ram_mb=16384,
            available_cpus=4,
            available_ram_mb=8192,
            total_gpus=1,
            available_gpus=2,
        )
