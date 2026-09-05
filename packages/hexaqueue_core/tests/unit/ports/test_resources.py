"""Unit tests for compute resource port models and contracts."""

import pytest
from hexaqueue_core.ports.resources import NodeCapacity


def test_node_capacity_valid():
    """Verify NodeCapacity fields and invariants."""
    cap = NodeCapacity(
        node_id="node-1",
        total_cpus=16,
        available_cpus=8,
        total_ram_mb=32768,
        available_ram_mb=16384,
        total_gpus=2,
        available_gpus=1,
        gpu_model="NVIDIA A100",
    )
    assert cap.node_id == "node-1"
    assert cap.total_cpus == 16
    assert cap.available_cpus == 8
    assert cap.gpu_model == "NVIDIA A100"


def test_node_capacity_exceeds_invariants():
    """Verify available resources cannot exceed total resources."""
    with pytest.raises(ValueError, match="available_cpus .* exceeds total_cpus"):
        NodeCapacity(
            node_id="node-1",
            total_cpus=4,
            available_cpus=8,
            total_ram_mb=8192,
            available_ram_mb=4096,
        )

    with pytest.raises(ValueError, match="available_ram_mb .* exceeds total_ram_mb"):
        NodeCapacity(
            node_id="node-1",
            total_cpus=8,
            available_cpus=4,
            total_ram_mb=8192,
            available_ram_mb=16384,
        )
