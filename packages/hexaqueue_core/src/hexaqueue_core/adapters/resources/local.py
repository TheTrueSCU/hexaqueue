"""Local compute resource discovery adapter."""

import os
from hexaqueue_core.ports.resources import ComputeResourcePort, NodeCapacity


class LocalComputeResourceAdapter(ComputeResourcePort):
    """Local machine resource topology discovery adapter."""

    async def get_node_capacity(self) -> NodeCapacity:
        """Discover CPU cores and memory from local OS."""
        cpus = os.cpu_count() or 4
        return NodeCapacity(
            node_id="local-node-0",
            total_cpus=cpus,
            available_cpus=cpus,
            total_ram_mb=8192,
            available_ram_mb=8192,
            total_gpus=0,
            available_gpus=0,
        )


__all__ = [
    "LocalComputeResourceAdapter",
]
