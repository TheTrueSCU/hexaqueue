"""Unit tests for FreeTierGovernorPort interface.

Notes/Architectural Intent:
    Verifies hexagonal boundary contract for FreeTierGovernorPort,
    confirming ABC enforcement and method signature expectations.
"""

from collections.abc import Sequence

import pytest

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.freetier import (
    LOCAL_FREE_TIER_PROFILE,
    CspFreeTierProfile,
    FreeTierBurnReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.ports.freetier import FreeTierGovernorPort


class DummyFreeTierGovernor(FreeTierGovernorPort):
    """Concrete dummy implementation for testing port contract."""

    @property
    def profile(self) -> CspFreeTierProfile:
        """Return dummy profile."""
        return LOCAL_FREE_TIER_PROFILE

    def validate_job_resource_request(self, job: JobSpec) -> None:
        """Dummy validator."""
        return

    def validate_region_placement(self, region: str | None) -> None:
        """Dummy placement validator."""
        return

    def check_cluster_headroom(
        self, active_jobs: Sequence[JobSpec], candidate: JobSpec
    ) -> bool:
        """Dummy headroom check."""
        return True

    def compute_burn_meter(
        self, active_jobs: Sequence[JobSpec], allocated_storage_mb: int = 0
    ) -> FreeTierBurnReport:
        """Dummy burn report."""
        return FreeTierBurnReport(
            provider=CspProvider.LOCAL,
            profile_name="Dummy",
            active_jobs_count=0,
            allocated_cpus=0,
            allocated_ram_mb=0,
            allocated_storage_mb=0,
            cpu_ceiling=2,
            ram_ceiling_mb=2048,
            storage_ceiling_mb=5120,
            cpu_utilization_pct=0.0,
            ram_utilization_pct=0.0,
            storage_utilization_pct=0.0,
            is_throttled=False,
        )


def test_free_tier_governor_port_cannot_be_instantiated_directly() -> None:
    """Verifies that FreeTierGovernorPort cannot be instantiated directly."""
    with pytest.raises(TypeError):
        FreeTierGovernorPort()  # type: ignore[abstract]


def test_dummy_free_tier_governor_satisfies_port() -> None:
    """Verifies that a subclass implementing all methods satisfies the port contract."""
    governor = DummyFreeTierGovernor()
    profile = governor.profile
    assert profile.provider == CspProvider.LOCAL

    headroom = governor.check_cluster_headroom(
        [], JobSpec(id="j1", run_id="r1", name="j1", command="echo 1")
    )
    assert headroom is True

    burn = governor.compute_burn_meter([])
    pct = burn.cpu_utilization_pct
    assert pct == 0.0
