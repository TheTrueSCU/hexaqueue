"""No-Op security quarantine adapter."""

from hexaqueue_core.domain.collateral import CollateralBundle, CollateralState
from hexaqueue_core.ports.security import SecurityQuarantinePort


class NoOpSecurityQuarantineAdapter(SecurityQuarantinePort):
    """No-op security quarantine adapter that approves all collateral."""

    async def scan_collateral(
        self, bundle: CollateralBundle
    ) -> tuple[CollateralState, str | None]:
        """Automatically approve collateral for local development."""
        return CollateralState.APPROVED, None


__all__ = [
    "NoOpSecurityQuarantineAdapter",
]
