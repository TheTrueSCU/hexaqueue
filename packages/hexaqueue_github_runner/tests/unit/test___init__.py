"""Test hexaqueue_github_runner package exports."""

import hexaqueue_github_runner


def test_hexaqueue_github_runner_package_exports() -> None:
    """Verify package can be imported and exports match __all__."""
    pkg = hexaqueue_github_runner
    assert pkg is not None
    exports = pkg.__all__
    assert "DynamicGitHubRunnerAutoscaler" in exports
    assert "GitHubWebhookAdapter" in exports
    assert "LabelTranslator" in exports
