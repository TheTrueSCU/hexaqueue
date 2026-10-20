"""Unit tests for SplitJoinBarrierPort contract."""

import inspect

from hexaqueue_workflow.ports.barrier import SplitJoinBarrierPort


def test_cannot_instantiate_abstract_split_join_barrier_port() -> None:
    """Verify SplitJoinBarrierPort is an abstract interface."""
    assert inspect.isabstract(SplitJoinBarrierPort)
    assert "await_barrier" in SplitJoinBarrierPort.__abstractmethods__
