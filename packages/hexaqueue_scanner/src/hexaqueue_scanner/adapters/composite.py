"""Composite quarantine scanner orchestrator adapter.

Notes/Architectural Intent:
    Implements SecurityQuarantinePort by orchestrating multiple software-managed
    engines (ClamAV, YARA, custom heuristics) and translating their findings
    into canonical CollateralState lifecycle transitions.
"""

import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.ports.security import SecurityQuarantinePort, SecurityScanResult
from hexaqueue_scanner.domain.config import ScannerConfig
from hexaqueue_scanner.domain.models import CompositeScanReport
from hexaqueue_scanner.ports.engine import MalwareScannerEnginePort


class CompositeQuarantineScannerAdapter(SecurityQuarantinePort):
    """Multi-engine security quarantine adapter.

    Args:
        engines: List of MalwareScannerEnginePort instances to evaluate.
        config: ScannerConfig specifying quarantine policies and timeouts.
    """

    def __init__(
        self,
        engines: list[MalwareScannerEnginePort] | None = None,
        config: ScannerConfig | None = None,
    ) -> None:
        self._engines = list(engines) if engines is not None else []
        self._config = config or ScannerConfig()

    def _resolve_file_path(self, staging_uri: str) -> Path:
        """Resolve a staging URI to a local Path."""
        if staging_uri.startswith("file://"):
            parsed = urlparse(staging_uri)
            return Path(unquote(parsed.path))
        return Path(staging_uri)

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Execute all configured scanning engines on a staged collateral bundle.

        Args:
            bundle: CollateralBundle awaiting quarantine verification.

        Returns:
            Tuple of (CollateralState.APPROVED, None) if clean, or
            (QUARANTINED/REJECTED, reason) if any threat is identified.
        """
        file_path = self._resolve_file_path(bundle.staging_uri)
        if not file_path.is_file():
            return (
                CollateralState.REJECTED,
                f"Staged collateral file does not exist: {file_path}",
            )

        failure_state = (
            CollateralState.QUARANTINED
            if self._config.quarantine_on_threat
            else CollateralState.REJECTED
        )

        for engine in self._engines:
            result = await engine.scan_file(file_path)
            if not result.is_clean:
                reason = (
                    f"Threat detected by {result.scanner_engine}: {result.threat_name}"
                )
                return failure_state, reason

        return CollateralState.APPROVED, None

    async def generate_report(self, bundle: CollateralBundle) -> CompositeScanReport:
        """Execute full engine inspection and return a detailed CompositeScanReport.

        Args:
            bundle: CollateralBundle to inspect.

        Returns:
            CompositeScanReport detailing individual findings and duration.
        """
        start_time = time.monotonic()
        file_path = self._resolve_file_path(bundle.staging_uri)
        results: list[SecurityScanResult] = []
        overall_clean = True
        quarantine_reason: str | None = None

        if not file_path.is_file():
            overall_clean = False
            quarantine_reason = f"Staged file missing: {file_path}"
        else:
            for engine in self._engines:
                res = await engine.scan_file(file_path)
                results.append(res)
                if not res.is_clean:
                    overall_clean = False
                    if quarantine_reason is None:
                        quarantine_reason = f"Threat detected by {res.scanner_engine}: {res.threat_name}"

        elapsed = time.monotonic() - start_time
        return CompositeScanReport(
            collateral_id=bundle.id,
            is_clean=overall_clean,
            duration_seconds=elapsed,
            results=results,
            quarantine_reason=quarantine_reason,
            scanned_at=datetime.now(UTC),
        )


__all__ = [
    "CompositeQuarantineScannerAdapter",
]
