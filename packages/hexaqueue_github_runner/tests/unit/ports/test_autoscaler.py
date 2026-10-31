"""Port tests for GitHubRunnerAutoscalerPort."""

import inspect

import pytest

from hexaqueue_github_runner.ports.autoscaler import (
    GitHubRunnerAutoscalerPort,
)


def test_github_runner_autoscaler_port_is_abstract() -> None:
    """Verify GitHubRunnerAutoscalerPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(GitHubRunnerAutoscalerPort)
    assert is_abs is True

    abstract_methods = GitHubRunnerAutoscalerPort.__abstractmethods__
    assert "handle_workflow_job" in abstract_methods
    assert "register_warm_pool" in abstract_methods
    assert "get_active_runner_count" in abstract_methods
    assert "get_warm_pool_status" in abstract_methods

    with pytest.raises(TypeError):
        GitHubRunnerAutoscalerPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]
