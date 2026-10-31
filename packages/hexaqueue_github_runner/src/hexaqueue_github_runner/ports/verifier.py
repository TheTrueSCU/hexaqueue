"""Abstract port interface for inbound webhook signature verification.

Notes/Architectural Intent:
    Decouples cryptographic HMAC verification mechanics from webhook routing,
    guaranteeing that unauthenticated or tampered payloads are rejected early.
"""

from abc import ABC, abstractmethod


class WebhookVerifierPort(ABC):
    """Abstract port for verifying inbound webhook digital signatures.

    Notes/Architectural Intent:
        Enforces constant-time cryptographic verification of HMAC signatures
        against webhook secrets to protect against timing attacks.
    """

    @abstractmethod
    def verify_signature(
        self,
        payload_bytes: bytes,
        signature_header: str | None,
        secret: str,
    ) -> bool:
        """Verify the cryptographic signature of raw webhook payload bytes.

        Args:
            payload_bytes: Raw HTTP request body bytes.
            signature_header: Header value received (e.g. 'sha256=...').
            secret: Configured shared webhook secret.

        Returns:
            True if signature is valid; raises exception otherwise.

        Raises:
            ValueError: If signature header is missing or malformed.
            PermissionError: If signature does not match computed HMAC.
        """


__all__ = [
    "WebhookVerifierPort",
]
