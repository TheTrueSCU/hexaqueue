"""Abstract port interface for remote test dispatch and outcome streaming.

Notes/Architectural Intent:
    Defines the contract for communicating with Hexaqueue cluster controllers,
    dispatching test slice jobs, and receiving remote execution telemetry.
"""

from abc import ABC, abstractmethod

from pytest_hexaqueue.domain.delta import WorkspaceDeltaBundle
from pytest_hexaqueue.domain.outcome import SliceOutcomeReport
from pytest_hexaqueue.domain.slice import TestRunSession


class HexaqueueTestDispatchPort(ABC):
    """Abstract port for dispatching distributed test sessions to Hexaqueue clusters."""

    @abstractmethod
    async def dispatch_run(
        self,
        session: TestRunSession,
        bundle: WorkspaceDeltaBundle | None = None,
    ) -> list[SliceOutcomeReport]:
        """Dispatch partitioned test slices across cluster workers and collect outcomes.

        Args:
            session: Configured TestRunSession containing slice specifications.
            bundle: Optional workspace delta bundle containing file manifests.

        Returns:
            List of SliceOutcomeReport instances returned from worker nodes.

        Raises:
            ConnectionError: If cluster controller is unreachable and fallback is disabled.
        """

    @abstractmethod
    async def find_collateral_by_checksum(self, sha256_checksum: str) -> str | None:
        """Query cluster CAS for an approved collateral bundle matching a SHA-256 digest.

        Args:
            sha256_checksum: Hexadecimal SHA-256 digest to look up.

        Returns:
            Collateral ID string if an approved bundle exists in CAS, or None on cache miss.
        """

    @abstractmethod
    async def upload_collateral_bundle(
        self,
        archive_bytes: bytes,
        sha256_checksum: str,
        filename: str = "workspace.tar.gz",
    ) -> str:
        """Register and stage a compressed collateral bundle in cluster CAS.

        Args:
            archive_bytes: Raw bytes of the compressed collateral archive.
            sha256_checksum: Precomputed SHA-256 digest of the archive bytes.
            filename: Artifact filename (defaults to 'workspace.tar.gz').

        Returns:
            Registered and promoted collateral ID.

        Raises:
            ConnectionError: If upload fails or cluster is unreachable.
        """

    @abstractmethod
    async def health_check(self) -> bool:
        """Check whether the Hexaqueue cluster controller is reachable and healthy.

        Returns:
            True if cluster is reachable and accepting jobs, False otherwise.
        """


__all__ = [
    "HexaqueueTestDispatchPort",
]
