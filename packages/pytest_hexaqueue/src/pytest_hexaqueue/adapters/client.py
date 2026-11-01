"""Test dispatch client adapters connecting pytest to Hexaqueue clusters.

Notes/Architectural Intent:
    Provides HTTP/REST communication with hexaqueue-server for remote execution
    alongside InMemoryTestDispatchClient for hermetic testing, local fallbacks,
    and property test verification.
"""

from typing import Any

import httpx

from pytest_hexaqueue.domain.delta import WorkspaceDeltaBundle
from pytest_hexaqueue.domain.outcome import (
    SliceOutcomeReport,
    TestOutcomeItem,
)
from pytest_hexaqueue.domain.slice import TestRunSession
from pytest_hexaqueue.ports.client import HexaqueueTestDispatchPort


class HexaqueueTestDispatchClient(HexaqueueTestDispatchPort):
    """Production client dispatching test runs to Hexaqueue cluster controllers.

    Args:
        server_url: Base URL of the Hexaqueue controller.
        timeout_seconds: HTTP request timeout limit.
        api_token: Optional Bearer authentication token for secure control-plane communication.

    Notes/Architectural Intent:
        Enforces separation of control-plane authentication from compute-plane CSP credentials.
        The client passes an optional Bearer token to authenticate with the Hexaqueue cluster
        controller without requiring any CSP admin keys or cloud SDK access on the test runner.
    """

    def __init__(
        self,
        server_url: str = "http://127.0.0.1:8000",
        timeout_seconds: float = 30.0,
        api_token: str | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.api_token = api_token

    def _headers(self) -> dict[str, str]:
        """Build request headers including Bearer authorization when configured."""
        headers: dict[str, str] = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def health_check(self) -> bool:
        """Query cluster controller health status endpoint."""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, headers=self._headers()
            ) as client:
                resp = await client.get(f"{self.server_url}/health")
                return resp.status_code == 200
        except (httpx.HTTPError, OSError):
            return False

    async def dispatch_run(
        self,
        session: TestRunSession,
        bundle: WorkspaceDeltaBundle | None = None,
    ) -> list[SliceOutcomeReport]:
        """Dispatch test slices to controller via HTTP API."""
        payload: dict[str, Any] = {
            "session_id": session.session_id,
            "pool": session.pool,
            "free_tier": session.free_tier,
            "container": session.container,
            "container_image": session.container_image,
            "coverage_sources": session.coverage_sources,
            "slices": [s.model_dump() for s in session.slices],
            "bundle": bundle.model_dump() if bundle else None,
        }

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout_seconds, headers=self._headers()
            ) as client:
                resp = await client.post(
                    f"{self.server_url}/api/v1/test/runs",
                    json=payload,
                )
                if resp.status_code != 200:
                    msg = f"Failed to submit test run: HTTP {resp.status_code} - {resp.text}"
                    raise ConnectionError(msg)

                raw_reports = resp.json().get("reports", [])
                return [SliceOutcomeReport.model_validate(r) for r in raw_reports]
        except (httpx.HTTPError, OSError) as exc:
            msg = f"Hexaqueue cluster at '{self.server_url}' is unreachable: {exc}"
            raise ConnectionError(msg) from exc


class InMemoryTestDispatchClient(HexaqueueTestDispatchPort):
    """In-memory simulation and test oracle for hermetic pytest execution.

    Notes/Architectural Intent:
        Enables offline developer workflows, dual-oracle state testing, and local fallback
        by simulating multi-worker distributed slice execution in-process.
    """

    def __init__(
        self,
        default_provider: str = "LOCAL",
        is_free_tier: bool = False,
        fail_nodeids: set[str] | None = None,
        is_healthy: bool = True,
    ) -> None:
        self.default_provider = default_provider
        self.is_free_tier = is_free_tier
        self.fail_nodeids = fail_nodeids or set()
        self.is_healthy = is_healthy
        self.dispatched_sessions: list[TestRunSession] = []

    async def health_check(self) -> bool:
        """Return configured simulated health status."""
        return self.is_healthy

    async def dispatch_run(
        self,
        session: TestRunSession,
        bundle: WorkspaceDeltaBundle | None = None,
    ) -> list[SliceOutcomeReport]:
        """Simulate distributed execution of each slice across mock providers."""
        if not self.is_healthy:
            msg = "Simulated cluster is unhealthy or unreachable"
            raise ConnectionError(msg)

        self.dispatched_sessions.append(session)
        reports: list[SliceOutcomeReport] = []

        # Simulated CSP pool cycle for multi-cloud demonstration
        providers = ["OCI", "GCP", "AWS", "AZURE", "LOCAL"]

        for slice_spec in session.slices:
            assigned_provider = (
                providers[slice_spec.slice_index % len(providers)]
                if session.free_tier
                else self.default_provider
            )

            outcomes: list[TestOutcomeItem] = []
            for nodeid in slice_spec.test_nodeids:
                if nodeid in self.fail_nodeids:
                    outcomes.append(
                        TestOutcomeItem(
                            nodeid=nodeid,
                            outcome="failed",
                            duration_seconds=0.05,
                            longrepr=f"AssertionError: Simulated test failure for {nodeid}",
                            stderr="Captured error log",
                        )
                    )
                else:
                    outcomes.append(
                        TestOutcomeItem(
                            nodeid=nodeid,
                            outcome="passed",
                            duration_seconds=0.02,
                            stdout="Captured stdout trace",
                        )
                    )

            reports.append(
                SliceOutcomeReport(
                    slice_id=slice_spec.slice_id,
                    slice_index=slice_spec.slice_index,
                    worker_id=f"worker-{assigned_provider.lower()}-{slice_spec.slice_index}",
                    provider=assigned_provider,
                    is_free_tier=session.free_tier,
                    outcomes=outcomes,
                    duration_seconds=max(0.1, len(slice_spec.test_nodeids) * 0.02),
                )
            )

        return reports


__all__ = [
    "HexaqueueTestDispatchClient",
    "InMemoryTestDispatchClient",
]
