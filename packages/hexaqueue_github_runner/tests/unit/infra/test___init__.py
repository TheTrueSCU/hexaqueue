"""Test infra package exports."""

import hexaqueue_github_runner.infra as infra


def test_infra_exports() -> None:
    """Verify infra package exports."""
    exports = infra.__all__
    assert "WebhookActionResponse" in exports
    assert "create_github_webhook_router" in exports
