"""Test ports package exports."""

import hexaqueue_github_runner.ports as ports


def test_ports_exports() -> None:
    """Verify ports package exports."""
    exports = ports.__all__
    assert "GitHubApiClientPort" in exports
    assert "GitHubRunnerAutoscalerPort" in exports
    assert "WebhookVerifierPort" in exports
