"""Port tests for GitHubApiClientPort."""

import inspect

import pytest

from hexaqueue_github_runner.ports.client import GitHubApiClientPort


def test_github_api_client_port_is_abstract() -> None:
    """Verify GitHubApiClientPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(GitHubApiClientPort)
    assert is_abs is True

    abstract_methods = GitHubApiClientPort.__abstractmethods__
    assert "generate_installation_token" in abstract_methods
    assert "generate_jit_runner_config" in abstract_methods
    assert "post_workflow_job_annotation" in abstract_methods

    with pytest.raises(TypeError):
        GitHubApiClientPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]
