"""Unit tests for local compute resource adapter."""

import pytest
from hexaqueue_core.adapters.resources.local import LocalComputeResourceAdapter


@pytest.mark.asyncio
async def test_local_compute_resource_discovery():
    """Verify node capacity discovery returns valid core and memory values."""
    resource_port = LocalComputeResourceAdapter()
    capacity = await resource_port.get_node_capacity()
    assert capacity.total_cpus >= 1
    assert capacity.available_cpus >= 1
    assert capacity.total_ram_mb > 0
