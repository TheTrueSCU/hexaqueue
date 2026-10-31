"""Test domain package exports."""

import hexaqueue_github_runner.domain as domain


def test_domain_exports() -> None:
    """Verify domain package exports."""
    exports = domain.__all__
    assert "GitHubWorkflowJobPayload" in exports
    assert "LabelTranslator" in exports
    assert "JitRunnerConfig" in exports
