"""Test adapters package exports."""

import hexaqueue_github_runner.adapters as adapters


def test_adapters_exports() -> None:
    """Verify adapters package exports."""
    exports = adapters.__all__
    assert "DynamicGitHubRunnerAutoscaler" in exports
    assert "GitHubApiClient" in exports
    assert "GitHubWebhookAdapter" in exports
    assert "HmacSha256WebhookVerifier" in exports
    assert "InMemoryGitHubApiClient" in exports
    assert "NaiveAutoscalerOracle" in exports
