"""Unit tests for cryptographic HMAC webhook verifier."""

import hashlib
import hmac

import pytest

from hexaqueue_github_runner.adapters.crypto import HmacSha256WebhookVerifier


def test_valid_signature_with_prefix() -> None:
    """Test verifying signature with sha256= prefix."""
    verifier = HmacSha256WebhookVerifier()
    payload = b'{"action":"queued"}'
    secret = "super-secret-key"
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    header = f"sha256={expected}"

    res = verifier.verify_signature(payload, header, secret)
    assert res is True


def test_valid_signature_without_prefix() -> None:
    """Test verifying signature without sha256= prefix."""
    verifier = HmacSha256WebhookVerifier()
    payload = b'{"action":"completed"}'
    secret = "secret-123"
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    res = verifier.verify_signature(payload, expected, secret)
    assert res is True


def test_invalid_signature_raises_permission_error() -> None:
    """Test tampered payload or invalid signature raises PermissionError."""
    verifier = HmacSha256WebhookVerifier()
    payload = b'{"action":"queued"}'
    secret = "secret-key"

    with pytest.raises(PermissionError, match="Invalid webhook HMAC"):
        verifier.verify_signature(payload, "sha256=badbadbad", secret)


def test_missing_header_raises_value_error() -> None:
    """Test missing signature header raises ValueError."""
    verifier = HmacSha256WebhookVerifier()
    with pytest.raises(ValueError, match="Missing required"):
        verifier.verify_signature(b"payload", None, "secret")


def test_empty_secret_raises_value_error() -> None:
    """Test empty secret raises ValueError."""
    verifier = HmacSha256WebhookVerifier()
    with pytest.raises(ValueError, match="Webhook secret must not be empty"):
        verifier.verify_signature(b"payload", "sha256=abc", "")
