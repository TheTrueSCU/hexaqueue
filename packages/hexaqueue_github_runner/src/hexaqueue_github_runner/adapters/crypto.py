"""Cryptographic HMAC signature verifier for GitHub webhooks.

Notes/Architectural Intent:
    Implements constant-time signature validation for 'X-Hub-Signature-256'
    headers in compliance with GitHub Webhook security specifications.
"""

import hashlib
import hmac
from typing import Final

from hexaqueue_github_runner.ports.verifier import WebhookVerifierPort

_SHA256_PREFIX: Final[str] = "sha256="


class HmacSha256WebhookVerifier(WebhookVerifierPort):
    """Verifies HMAC SHA-256 signatures on inbound GitHub webhook payloads.

    Notes/Architectural Intent:
        Uses hmac.compare_digest to prevent side-channel timing attacks when
        verifying authenticity of webhook deliveries.
    """

    def verify_signature(
        self,
        payload_bytes: bytes,
        signature_header: str | None,
        secret: str,
    ) -> bool:
        """Verify the cryptographic signature of raw webhook payload bytes.

        Args:
            payload_bytes: Raw HTTP request body bytes.
            signature_header: Header value received ('sha256=...').
            secret: Configured shared webhook secret.

        Returns:
            True if signature matches computed HMAC.

        Raises:
            ValueError: If signature_header is empty or secret is empty.
            PermissionError: If signature does not match computed HMAC.
        """
        if not secret:
            msg = "Webhook secret must not be empty"
            raise ValueError(msg)

        if not signature_header:
            msg = "Missing required 'X-Hub-Signature-256' header"
            raise ValueError(msg)

        sig_value = (
            signature_header[len(_SHA256_PREFIX) :]
            if signature_header.startswith(_SHA256_PREFIX)
            else signature_header
        )

        expected_mac = hmac.new(
            secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(sig_value.lower(), expected_mac.lower()):
            msg = "Invalid webhook HMAC SHA-256 signature"
            raise PermissionError(msg)

        return True


__all__ = [
    "HmacSha256WebhookVerifier",
]
