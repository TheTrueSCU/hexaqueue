"""Domain models for security analysis reporting.

Notes/Architectural Intent:
    Encapsulates aggregated scan findings across multiple software-managed
    or cloud-native security inspection engines.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from hexaqueue_core.ports.security import SecurityScanResult


class CompositeScanReport(BaseModel):
    """Consolidated security analysis report for a scanned collateral bundle.

    Args:
        collateral_id: Identifier of the examined collateral bundle.
        is_clean: True if all active scan engines found no threats or policy violations.
        results: Detailed per-engine scan results.
        scanned_at: Timestamp when inspection completed.
        duration_seconds: Wall-clock duration of the scanning pipeline in seconds.
        quarantine_reason: Consolidated explanation if any threat was detected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    collateral_id: str = Field(description="Associated collateral bundle ID")
    duration_seconds: float = Field(
        ge=0.0, description="Total scan execution duration in seconds"
    )
    is_clean: bool = Field(description="True if artifact is certified safe and clean")
    quarantine_reason: str | None = Field(
        default=None, description="Detailed explanation if quarantined or rejected"
    )
    results: list[SecurityScanResult] = Field(
        default_factory=list, description="Individual scanner engine findings"
    )
    scanned_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Scan completion timestamp",
    )


class ScannerMetrics(BaseModel):
    """Real-time operational metrics for the scanner daemon.

    Args:
        total_scans: Total number of bundles processed.
        approved_scans: Number of bundles verified clean and promoted to active storage.
        quarantined_scans: Number of bundles quarantined due to detected threats.
        rejected_scans: Number of bundles rejected due to errors or invalid formats.
        error_scans: Number of scans that failed with execution errors.
        total_duration_seconds: Cumulative duration in seconds across all scans.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    approved_scans: int = Field(
        default=0, ge=0, description="Total clean approved scans"
    )
    error_scans: int = Field(default=0, ge=0, description="Total scan execution errors")
    quarantined_scans: int = Field(
        default=0, ge=0, description="Total quarantined threat detections"
    )
    rejected_scans: int = Field(
        default=0, ge=0, description="Total rejected/corrupt artifact scans"
    )
    total_duration_seconds: float = Field(
        default=0.0, ge=0.0, description="Cumulative scan wall-clock time in seconds"
    )
    total_scans: int = Field(
        default=0, ge=0, description="Total collateral bundles processed"
    )

    @property
    def average_duration_seconds(self) -> float:
        """Calculate average scan duration across all processed bundles."""
        if self.total_scans == 0:
            return 0.0
        return self.total_duration_seconds / self.total_scans


__all__ = [
    "CompositeScanReport",
    "ScannerMetrics",
]
