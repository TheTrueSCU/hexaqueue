"""Security, zero-trust identity, envelope encryption, and audit port interfaces.

Notes/Architectural Intent:
    Defines the contracts for zero-trust microservice attestation (SPIFFE/SPIRE),
    cryptographic envelope encryption (AES-256-GCM / KMS DEK wrapping),
    security quarantine evaluation, and immutable SIEM boundary access logging.
"""

from abc import ABC, abstractmethod
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.domain.security import (
    BoundaryAuditRecord,
    EncryptedEnvelope,
    SpiffeId,
)


class SecurityScanResult(BaseModel):
    """Result of a collateral security and malware inspection scan.

    Args:
        is_clean: True if no threats or policy violations were detected.
        threat_name: Optional name of the detected threat/malware signature.
        scanner_engine: Name/version of the engine that performed the scan.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_clean: bool = Field(description="True if artifact is safe and clean")
    scanner_engine: str = Field(description="Name and version of the scanning engine")
    threat_name: str | None = Field(
        default=None, description="Identified threat or virus signature"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate scan result invariants."""
        if not self.is_clean and not self.threat_name:
            msg = "threat_name must be provided when artifact is not clean"
            raise ValueError(msg)
        if not self.scanner_engine.strip():
            msg = "scanner_engine cannot be empty"
            raise ValueError(msg)
        return self


class SecurityQuarantinePort(ABC):
    """Abstract port interface for security quarantine and malware scanning."""

    @abstractmethod
    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Perform security scan on a staged collateral bundle.

        Args:
            bundle: CollateralBundle to inspect.

        Returns:
            Tuple of (NextCollateralState, OptionalQuarantineReason).
            NextCollateralState will be APPROVED if clean, or QUARANTINED / REJECTED if infected.
        """


class WorkloadIdentityPort(ABC):
    """Port interface for SPIFFE / SPIRE workload identity attestation."""

    @abstractmethod
    def get_spiffe_id(self) -> SpiffeId | None:
        """Retrieve the local attested SPIFFE identity of the running workload.

        Returns:
            SpiffeId value object if attested, or None if unauthenticated.
        """

    @abstractmethod
    def fetch_jwt_svid(self, audience: set[str]) -> str:
        """Fetch a cryptographically signed JWT-SVID for outbound RPC calls.

        Args:
            audience: Target audience set.

        Returns:
            Signed JWT-SVID token string.
        """

    @abstractmethod
    def validate_jwt_svid(self, token: str, audience: set[str]) -> SpiffeId:
        """Validate an inbound JWT-SVID token and return the verified caller identity.

        Args:
            token: Raw JWT-SVID token string.
            audience: Expected audience set.

        Returns:
            Verified SpiffeId of the caller.
        """


class SpiffeAuthorizerPort(ABC):
    """Port interface for evaluating zero-trust boundary authorization policies."""

    @abstractmethod
    async def authorize(
        self,
        spiffe_id: SpiffeId | str | None,
        boundary: str,
        action: str = "EXECUTE",
    ) -> bool:
        """Evaluate whether a caller is authorized for a target boundary and action.

        Args:
            spiffe_id: Calling identity (SpiffeId object, URI string, or None).
            boundary: Target boundary identifier (e.g. 'api:worker:lease').
            action: Semantic action performed (defaults to 'EXECUTE').

        Returns:
            True if authorized, False otherwise.
        """


class EnvelopeEncryptionPort(ABC):
    """Port interface for envelope encryption with Data Encryption Keys (DEKs)."""

    @abstractmethod
    async def encrypt(
        self,
        data: bytes,
        key_id: str | None = None,
        context: dict[str, str] | None = None,
    ) -> EncryptedEnvelope:
        """Encrypt payload data using a freshly minted ephemeral DEK wrapped by a master KEK.

        Args:
            data: Raw plaintext payload bytes.
            key_id: Optional master key identifier (defaults to active KEK).
            context: Optional Additional Authenticated Data (AAD) dictionary.

        Returns:
            EncryptedEnvelope holding ciphertext, wrapped DEK, IV, tag, and context.
        """

    @abstractmethod
    async def decrypt(self, envelope: EncryptedEnvelope) -> bytes:
        """Decrypt an envelope by unwrapping its DEK and deciphering the payload.

        Args:
            envelope: EncryptedEnvelope containing ciphertext and wrapped DEK.

        Returns:
            Decrypted plaintext bytes.
        """


class BoundaryAuditLoggerPort(ABC):
    """Port interface for immutable boundary access audit logging."""

    @abstractmethod
    async def log_access(self, record: BoundaryAuditRecord) -> None:
        """Record an immutable access event for security audit and SIEM forwarding.

        Args:
            record: BoundaryAuditRecord instance.
        """

    @abstractmethod
    async def get_recent_records(self, limit: int = 100) -> list[BoundaryAuditRecord]:
        """Retrieve recent audit access records for diagnostic query and audit trail verification.

        Args:
            limit: Maximum count of records to return.

        Returns:
            List of BoundaryAuditRecord items ordered chronologically.
        """


__all__ = [
    "BoundaryAuditLoggerPort",
    "EnvelopeEncryptionPort",
    "SecurityQuarantinePort",
    "SecurityScanResult",
    "SpiffeAuthorizerPort",
    "WorkloadIdentityPort",
]
