"""Security and malware inspection port interface.

Notes/Architectural Intent:
    Defines the contract for inspecting uploaded collateral files before they are
    promoted to APPROVED active storage. Supports Software-Managed (hexaqueue-scanner /
    ClamAV / YARA) and Native Deference (AWS GuardDuty / S3 Malware Protection).
"""

from abc import ABC, abstractmethod
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState


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
