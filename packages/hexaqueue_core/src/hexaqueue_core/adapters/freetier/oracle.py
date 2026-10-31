"""Naive reference oracle for Multi-CSP Free-Tier Mesh testing.

Notes/Architectural Intent:
    Serves as an independent mathematical reference model for differential
    fuzzing via Hypothesis, validating that MultiCspFreeTierGovernor preserves
    resource ceilings and allocation states.
"""


class NaiveFreeTierMeshOracle:
    r"""Minimal reference state machine for dual-oracle property verification.

    Notes/Architectural Intent:
        Implements naive sequential state tracking to cross-evaluate against
        MultiCspFreeTierGovernor ($f_{\text{prod}}(x) \equiv f_{\text{oracle}}(x)$).
    """

    def __init__(self, limits: dict[str, tuple[int, int]] | None = None) -> None:
        # provider -> (max_cpus, max_ram_mb)
        self.limits: dict[str, tuple[int, int]] = limits or {
            "OCI": (4, 24576),
            "GCP": (2, 1024),
            "AWS": (1, 1024),
            "AZURE": (1, 1024),
            "LOCAL": (2, 2048),
        }
        self.allocations: dict[str, tuple[str, int, int]] = {}

    def step_allocate(
        self,
        job_id: str,
        cpus: int,
        ram_mb: int,
        preferred: str | None = None,
    ) -> str | None:
        """Attempt to allocate job on first qualifying provider."""
        if job_id in self.allocations:
            return None

        providers = list(self.limits.keys())
        if preferred and preferred in providers:
            providers.remove(preferred)
            providers.insert(0, preferred)

        for prov in providers:
            max_c, max_r = self.limits[prov]
            if cpus > max_c or ram_mb > max_r:
                continue

            current_c = sum(c for p, c, _ in self.allocations.values() if p == prov)
            current_r = sum(r for p, _, r in self.allocations.values() if p == prov)

            if (current_c + cpus <= max_c) and (current_r + ram_mb <= max_r):
                self.allocations[job_id] = (prov, cpus, ram_mb)
                return prov

        return None

    def step_release(self, job_id: str) -> bool:
        """Release allocated job."""
        if job_id in self.allocations:
            del self.allocations[job_id]
            return True
        return False

    @property
    def total_allocated_cpus(self) -> int:
        """Total CPUs allocated across all providers."""
        return sum(c for _, c, _ in self.allocations.values())

    @property
    def total_allocated_ram(self) -> int:
        """Total RAM in MB allocated across all providers."""
        return sum(r for _, _, r in self.allocations.values())

    @property
    def active_job_count(self) -> int:
        """Total active jobs."""
        return len(self.allocations)


__all__ = [
    "NaiveFreeTierMeshOracle",
]
