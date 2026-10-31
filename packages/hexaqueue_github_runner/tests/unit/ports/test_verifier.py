"""Port tests for WebhookVerifierPort."""

import inspect

import pytest

from hexaqueue_github_runner.ports.verifier import WebhookVerifierPort


def test_webhook_verifier_port_is_abstract() -> None:
    """Verify WebhookVerifierPort cannot be instantiated directly and is abstract."""
    is_abs = inspect.isabstract(WebhookVerifierPort)
    assert is_abs is True

    abstract_methods = WebhookVerifierPort.__abstractmethods__
    assert "verify_signature" in abstract_methods

    with pytest.raises(TypeError):
        WebhookVerifierPort()  # ty: ignore[call-non-callable] # type: ignore[abstract]
