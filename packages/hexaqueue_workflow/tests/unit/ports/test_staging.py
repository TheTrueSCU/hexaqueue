"""Tests for ArtifactStagingPort interface contract."""

import inspect
from typing import Any

from hexaqueue_workflow.ports.staging import ArtifactStagingPort


class DummyStagingAdapter(ArtifactStagingPort):
    """Concrete dummy implementation to verify abstract methods."""

    def stage_artifact(self, run_id: str, step_name: str, payload: Any) -> Any:
        return payload

    def retrieve_artifact(self, payload: Any) -> Any:
        return payload

    def should_stage(self, payload: Any) -> bool:
        return False


def test_artifact_staging_port_abstract_interface() -> None:
    """Verify that ArtifactStagingPort requires all abstract methods."""
    assert inspect.isabstract(ArtifactStagingPort)
    assert "stage_artifact" in ArtifactStagingPort.__abstractmethods__

    adapter = DummyStagingAdapter()
    res = adapter.stage_artifact("run-1", "step-1", "data")
    assert res == "data"
    res_ret = adapter.retrieve_artifact("data")
    assert res_ret == "data"
    res_stage = adapter.should_stage("data")
    assert res_stage is False
