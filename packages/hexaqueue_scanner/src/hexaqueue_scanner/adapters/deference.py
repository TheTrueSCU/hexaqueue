"""Provider-Native Deference security and quarantine adapters.

Notes/Architectural Intent:
    Implements SecurityQuarantinePort by deferring to native cloud object storage
    malware inspection services (Amazon GuardDuty Malware Protection for S3 and
    Microsoft Defender for Storage on Azure Blobs). Eliminates redundant worker
    bandwidth and compute overhead by inspecting serverless storage metadata tags.
"""

from collections.abc import Awaitable, Callable

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.ports.security import SecurityQuarantinePort
from hexaqueue_scanner.domain.config import CloudDeferenceConfig


class AwsGuardDutyQuarantineAdapter(SecurityQuarantinePort):
    """Quarantine adapter deferring to Amazon GuardDuty Malware Protection for S3.

    Args:
        config: CloudDeferenceConfig specifying S3 tag keys and verdict values.
        tag_fetcher: Optional async callable retrieving S3 object tags for a staging URI.
    """

    def __init__(
        self,
        config: CloudDeferenceConfig | None = None,
        tag_fetcher: Callable[[str], Awaitable[dict[str, str]]] | None = None,
    ) -> None:
        self._config = config or CloudDeferenceConfig()
        self._tag_fetcher = tag_fetcher

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Inspect AWS GuardDuty S3 tags for malware scan verdict.

        Args:
            bundle: CollateralBundle staged in Amazon S3.

        Returns:
            Tuple of (CollateralState.APPROVED, None) if clean, or
            (CollateralState.QUARANTINED, reason) if threat detected or scan pending.
        """
        if not self._config.aws_guardduty_enabled:
            return CollateralState.APPROVED, None

        tags: dict[str, str] = {}
        if self._tag_fetcher is not None:
            try:
                tags = await self._tag_fetcher(bundle.staging_uri)
            except Exception as e:
                msg = f"Failed to retrieve AWS S3 tags for {bundle.filename}: {e}"
                return CollateralState.QUARANTINED, msg

        verdict = tags.get(self._config.aws_tag_key)
        if verdict in self._config.aws_clean_tag_values:
            return CollateralState.APPROVED, None

        if verdict in self._config.aws_threat_tag_values:
            reason = f"AWS GuardDuty detected threat in {bundle.filename} (verdict: {verdict})"
            return CollateralState.QUARANTINED, reason

        missing_reason = (
            f"AWS GuardDuty scan verdict missing or pending for {bundle.filename} "
            f"(tag: '{self._config.aws_tag_key}', value: '{verdict}')"
        )
        return CollateralState.QUARANTINED, missing_reason


class AzureDefenderQuarantineAdapter(SecurityQuarantinePort):
    """Quarantine adapter deferring to Microsoft Defender for Storage.

    Args:
        config: CloudDeferenceConfig specifying Azure Blob Index tag keys and values.
        tag_fetcher: Optional async callable retrieving Blob Index tags for a staging URI.
    """

    def __init__(
        self,
        config: CloudDeferenceConfig | None = None,
        tag_fetcher: Callable[[str], Awaitable[dict[str, str]]] | None = None,
    ) -> None:
        self._config = config or CloudDeferenceConfig()
        self._tag_fetcher = tag_fetcher

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Inspect Azure Defender Blob Index tags for malware scan verdict.

        Args:
            bundle: CollateralBundle staged in Azure Blob Storage.

        Returns:
            Tuple of (CollateralState.APPROVED, None) if clean, or
            (CollateralState.QUARANTINED, reason) if threat detected or scan pending.
        """
        if not self._config.azure_defender_enabled:
            return CollateralState.APPROVED, None

        tags: dict[str, str] = {}
        if self._tag_fetcher is not None:
            try:
                tags = await self._tag_fetcher(bundle.staging_uri)
            except Exception as e:
                msg = f"Failed to retrieve Azure Blob tags for {bundle.filename}: {e}"
                return CollateralState.QUARANTINED, msg

        verdict = tags.get(self._config.azure_tag_key)
        if verdict in self._config.azure_clean_tag_values:
            return CollateralState.APPROVED, None

        if verdict in self._config.azure_threat_tag_values:
            reason = (
                f"Azure Defender for Storage detected malware in {bundle.filename} "
                f"(verdict: {verdict})"
            )
            return CollateralState.QUARANTINED, reason

        missing_reason = (
            f"Azure Defender scan verdict missing or pending for {bundle.filename} "
            f"(tag: '{self._config.azure_tag_key}', value: '{verdict}')"
        )
        return CollateralState.QUARANTINED, missing_reason


class PassThroughSecurityQuarantineAdapter(SecurityQuarantinePort):
    """Zero-overhead pass-through adapter for pre-trusted or air-gapped environments."""

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Approve all collateral bundles unconditionally.

        Args:
            bundle: Staged CollateralBundle.

        Returns:
            Tuple of (CollateralState.APPROVED, None).
        """
        return CollateralState.APPROVED, None


__all__ = [
    "AwsGuardDutyQuarantineAdapter",
    "AzureDefenderQuarantineAdapter",
    "PassThroughSecurityQuarantineAdapter",
]
