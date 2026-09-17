"""Barrier adapters package for hexaqueue_workflow."""

from hexaqueue_workflow.adapters.barrier.grpc import GrpcSplitJoinBarrierAdapter

__all__ = [
    "GrpcSplitJoinBarrierAdapter",
]
