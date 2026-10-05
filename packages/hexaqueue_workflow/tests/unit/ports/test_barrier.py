"""Unit tests for SplitJoinBarrierPort contract."""

import pytest

from hexaqueue_workflow.ports.barrier import SplitJoinBarrierPort


def test_cannot_instantiate_abstract_split_join_barrier_port() -> None:
    """Verify SplitJoinBarrierPort cannot be instantiated directly without implementations."""
    with pytest.raises(TypeError):
        SplitJoinBarrierPort()  # type: ignore[abstract]
