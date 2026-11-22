"""HTTP remote controller adapter for distributed Hexaqueue clients.

Notes/Architectural Intent:
    Implements SchedulerControllerPort over HTTP against a separately running
    hexaqueue-server controller process so standalone dashboard and CLI deployments
    never disrupt active pipeline runs or compute worker leases.
"""

from collections.abc import Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

import httpx
from pydantic import SecretStr

from hexaqueue_core.domain.cqrs import (
    ClusterStatsReport,
    DeadLetterQueueReport,
    NodesReport,
    PresignedDownloadUrl,
)
from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.explainability import (
    FairShareTreeReport,
    SchedulingDecisionReport,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.retry import DeadLetterRecord
from hexaqueue_core.domain.suite import SuiteSpec
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_core.ports.logging import LogChunk
from hexaqueue_server.domain.memento import (
    DagRewindReport,
    PlacementSimulationReport,
    SchedulerMemento,
)
from hexaqueue_server.domain.models import RunStatusReport, RunSubmission
from hexaqueue_server.domain.placement import PlacementDecision
from hexaqueue_server.ports.controller import SchedulerControllerPort
from hexaqueue_worker.domain.pty import PtySessionInfo, PtySessionRequest


class HttpSchedulerControllerAdapter(SchedulerControllerPort):
    """Remote HTTP client adapter implementing SchedulerControllerPort.

    Args:
        base_url: Base URL of the central hexaqueue-server controller.
        admin_token: Optional admin bearer token wrapped in SecretStr.
        user_id: Acting service user identity forwarded via X-Hexaqueue-User.
        elevate: Whether to assert elevated privileges when calling controller APIs.
        timeout: HTTP request timeout in seconds.
        transport: Optional custom httpx transport (used for hermetic unit testing).

    Notes/Architectural Intent:
        Forwards CQRS controller calls to the central hexaqueue-server REST API
        (``/v1/*``) using ``httpx.AsyncClient``, preserving process isolation between
        the control plane, dashboard, and CLI clients. Supports task-local identity
        override via ``acting_as`` for per-command CLI authentication headers.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        *,
        admin_token: SecretStr | None = None,
        user_id: str = "dashboard",
        elevate: bool = True,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_token = admin_token
        self._user_id = user_id
        self._elevate = elevate
        self._timeout = timeout
        self._transport = transport
        self._auth_ctx: ContextVar[tuple[str, bool] | None] = ContextVar(
            f"http_controller_auth_{id(self)}", default=None
        )

    @contextmanager
    def acting_as(self, user_id: str, elevate: bool) -> Generator[None]:
        """Temporarily bind per-task caller identity headers for outbound HTTP calls.

        Args:
            user_id: Acting user identity for X-Hexaqueue-User header.
            elevate: Administrative elevation flag for X-Hexaqueue-Elevate header.

        Yields:
            None while the task-local ContextVar override is active.

        Notes/Architectural Intent:
            Ensures multi-user CLI invocations sharing a long-lived controller adapter
            propagate per-command ``--user`` and ``--admin`` flags safely across
            asyncio coroutines without mutating shared instance state.
        """
        token = self._auth_ctx.set((user_id, elevate))
        try:
            yield
        finally:
            self._auth_ctx.reset(token)

    def _headers(self) -> dict[str, str]:
        """Build outbound authentication and identity headers."""
        override = self._auth_ctx.get()
        uid, is_elevated = (
            override if override is not None else (self._user_id, self._elevate)
        )
        headers = {
            "X-Hexaqueue-User": uid,
            "X-Hexaqueue-Elevate": "true" if is_elevated else "false",
        }
        if self._admin_token is not None:
            headers["X-Hexaqueue-Admin-Token"] = self._admin_token.get_secret_value()
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an HTTP request against the remote controller API."""
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(),
                timeout=self._timeout,
                transport=self._transport,
            ) as client:
                response = await client.request(method, path, json=json_body)
        except httpx.HTTPError as exc:
            raise HexaqueueError(
                f"Failed to reach controller at {self._base_url}{path}: {exc}",
            ) from exc

        if response.is_error:
            detail = response.text
            try:
                payload = response.json()
                if isinstance(payload, dict) and "detail" in payload:
                    detail = str(payload["detail"])
            except ValueError:
                detail = response.text
            raise HexaqueueError(
                f"Controller HTTP {response.status_code} on {method} {path}: {detail}",
            )

        if not response.content:
            return None
        return response.json()

    async def submit_run(self, submission: RunSubmission) -> RunStatusReport:
        """Submit a DAG pipeline run to the remote controller.

        Args:
            submission: Complete RunSubmission specification.

        Returns:
            Initial RunStatusReport.

        Raises:
            HexaqueueError: If the controller rejects or fails the submission.
        """
        payload = {
            "run_spec": submission.run_spec.model_dump(mode="json"),
            "jobs": [job.model_dump(mode="json") for job in submission.jobs],
            "dependencies": submission.dependencies,
        }
        data = await self._request("POST", "/v1/runs", json_body=payload)
        return RunStatusReport.model_validate(data)

    async def submit_suite(self, suite_spec: SuiteSpec) -> RunStatusReport:
        """Compile and submit a hierarchical suite workload to the remote controller.

        Args:
            suite_spec: Hierarchical SuiteSpec payload.

        Returns:
            Initial RunStatusReport.

        Raises:
            HexaqueueError: If the controller rejects or fails suite submission.
        """
        payload = {"suite_spec": suite_spec.model_dump(mode="json")}
        data = await self._request("POST", "/v1/suites", json_body=payload)
        return RunStatusReport.model_validate(data)

    async def get_run_status(self, run_id: str) -> RunStatusReport:
        """Retrieve aggregated run status from the remote controller.

        Args:
            run_id: Unique pipeline run identifier.

        Returns:
            Current RunStatusReport.

        Raises:
            HexaqueueError: If the run is not found or controller request fails.
        """
        data = await self._request("GET", f"/v1/runs/{run_id}")
        return RunStatusReport.model_validate(data)

    async def get_job(self, job_id: str) -> JobSpec:
        """Retrieve metadata and status for an individual job.

        Args:
            job_id: Unique job identifier.

        Returns:
            JobSpec instance.

        Raises:
            HexaqueueError: If the job is not found or controller request fails.
        """
        data = await self._request("GET", f"/v1/jobs/{job_id}")
        return JobSpec.model_validate(data)

    async def update_job_outcome(
        self,
        job_id: str,
        outcome: TerminalOutcome,
        reason: str | None = None,
        walltime_seconds: float | None = None,
        consumed_credits: float | None = None,
    ) -> None:
        """Record the terminal outcome of an executed job on the remote controller.

        Args:
            job_id: Finished job identifier.
            outcome: Final TerminalOutcome.
            reason: Optional explanation or error message.
            walltime_seconds: Optional executed walltime in seconds.
            consumed_credits: Optional consumed credits.

        Raises:
            HexaqueueError: If the controller rejects the outcome update.
        """
        endpoint = (
            f"/v1/jobs/{job_id}/complete"
            if outcome == TerminalOutcome.COMPLETED
            else f"/v1/jobs/{job_id}/fail"
        )
        await self._request(
            "POST",
            endpoint,
            json_body={
                "reason": reason,
                "walltime_seconds": walltime_seconds,
                "consumed_credits": consumed_credits,
            },
        )

    async def cancel_run(self, run_id: str) -> RunStatusReport:
        """Cancel an in-flight run on the remote controller.

        Args:
            run_id: Pipeline run identifier to cancel.

        Returns:
            Updated RunStatusReport showing CANCELLED state.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("POST", f"/v1/runs/{run_id}/cancel")
        return RunStatusReport.model_validate(data)

    async def list_jobs(self) -> list[JobSpec]:
        """Retrieve all currently registered jobs from the remote controller.

        Returns:
            List of all JobSpec instances.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("GET", "/v1/jobs")
        return [JobSpec.model_validate(item) for item in data]

    async def get_logs(self, job_id: str, *, tail: int | None = None) -> list[LogChunk]:
        """Retrieve execution log chunks for a job from the remote controller.

        Args:
            job_id: Target job identifier.
            tail: Optional maximum number of trailing log chunks.

        Returns:
            List of LogChunk entries.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        path = f"/v1/jobs/{job_id}/logs"
        if tail is not None:
            path = f"{path}?tail={tail}"
        data = await self._request("GET", path)
        return [LogChunk.model_validate(item) for item in data]

    async def get_job_log_download_url(
        self, job_id: str, *, expires_in_seconds: int = 900
    ) -> str:
        """Retrieve a preauthenticated log download URL from the remote controller.

        Args:
            job_id: Target job identifier.
            expires_in_seconds: Validity TTL for the signed download link.

        Returns:
            Direct presigned download URL string.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request(
            "GET",
            f"/v1/jobs/{job_id}/logs/download-url?expires_in_seconds={expires_in_seconds}",
        )
        return PresignedDownloadUrl.model_validate(data).download_url

    async def list_runs(self, *, limit: int | None = None) -> list[RunStatusReport]:
        """Retrieve currently registered pipeline runs from the remote controller.

        Args:
            limit: Optional maximum count of runs to return.

        Returns:
            List of RunStatusReport instances.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        path = "/v1/runs" if limit is None else f"/v1/runs?limit={limit}"
        data = await self._request("GET", path)
        return [RunStatusReport.model_validate(item) for item in data]

    async def cancel_job(self, job_id: str) -> JobSpec:
        """Cancel an individual job on the remote controller.

        Args:
            job_id: Unique job identifier.

        Returns:
            Updated JobSpec with CANCELLED outcome.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("POST", f"/v1/jobs/{job_id}/cancel")
        return JobSpec.model_validate(data)

    async def hold_job(self, job_id: str) -> JobSpec:
        """Place an administrative hold on a job via the remote controller.

        Args:
            job_id: Unique job identifier.

        Returns:
            Updated JobSpec in BLOCKED state.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("POST", f"/v1/jobs/{job_id}/hold")
        return JobSpec.model_validate(data)

    async def release_job(self, job_id: str) -> JobSpec:
        """Release an administrative hold on a job via the remote controller.

        Args:
            job_id: Unique job identifier.

        Returns:
            Updated JobSpec returned to PENDING or appropriate state.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("POST", f"/v1/jobs/{job_id}/release")
        return JobSpec.model_validate(data)

    async def explain_job(self, job_id: str) -> SchedulingDecisionReport:
        """Retrieve placement and priority diagnostics for a job from the remote controller.

        Args:
            job_id: Unique job identifier.

        Returns:
            SchedulingDecisionReport from ``GET /v1/jobs/{job_id}/explain``.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("GET", f"/v1/jobs/{job_id}/explain")
        return SchedulingDecisionReport.model_validate(data)

    async def get_fairshare_tree(self) -> FairShareTreeReport:
        """Retrieve the fair-share hierarchy tree from the remote controller.

        Returns:
            FairShareTreeReport from ``GET /v1/fairshare``.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("GET", "/v1/fairshare")
        return FairShareTreeReport.model_validate(data)

    async def get_queue_stats(self) -> ClusterStatsReport:
        """Retrieve aggregate cluster statistics from the remote controller.

        Returns:
            ClusterStatsReport from ``GET /v1/stats``.

        Raises:
            HexaqueueError: If the controller request fails.

        Notes/Architectural Intent:
            Ensures remote CLI and dashboard clients read authoritative active-worker
            and backlog counters computed by the remote control plane rather than
            synthesizing counts locally.
        """
        data = await self._request("GET", "/v1/stats")
        return ClusterStatsReport.model_validate(data)

    async def register_node(self, profile: ComputeNodeProfile) -> None:
        """Register a compute worker node with the remote controller.

        Args:
            profile: Initial compute node profile and resource capacity.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        await self._request(
            "POST",
            "/v1/nodes/register",
            json_body={"profile": profile.model_dump(mode="json")},
        )

    async def heartbeat_node(
        self,
        worker_id: str,
        active_job_ids: list[str] | None = None,
        cached_collateral_hashes: list[str] | None = None,
        pulse: NodeTelemetryPulse | None = None,
    ) -> ComputeNodeProfile:
        """Record a heartbeat pulse from a compute worker node.

        Args:
            worker_id: Unique worker node identifier.
            active_job_ids: Optional list of in-flight job IDs on the worker.
            cached_collateral_hashes: Optional list of CAS hashes cached on the node.
            pulse: Optional telemetry pulse emitted by the worker node.

        Returns:
            Updated ComputeNodeProfile instance.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        payload: dict[str, Any] = {
            "worker_id": worker_id,
            "active_job_ids": active_job_ids or [],
            "cached_collateral_hashes": cached_collateral_hashes or [],
        }
        if pulse is not None:
            payload["pulse"] = pulse.model_dump(mode="json")
        data = await self._request("POST", "/v1/nodes/heartbeat", json_body=payload)
        return ComputeNodeProfile.model_validate(data)

    async def list_nodes(self) -> list[ComputeNodeProfile]:
        """Retrieve all registered compute worker nodes from the remote controller.

        Returns:
            List of ComputeNodeProfile instances.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("GET", "/v1/nodes/profiles")
        return NodesReport.model_validate(data).nodes

    async def list_node_pulses(self) -> list[NodeTelemetryPulse]:
        """Retrieve live worker NodeTelemetryPulse records from the remote controller.

        Returns:
            List of live ``NodeTelemetryPulse`` records from ``GET /v1/nodes``.

        Raises:
            HexaqueueError: If the controller request fails.

        Notes/Architectural Intent:
            Fetches live CPU, RAM, scratch, and active-job telemetry directly from
            the controller's ``/v1/nodes`` endpoint instead of reconstructing
            synthetic zeros from static ``ComputeNodeProfile`` records.
        """
        data = await self._request("GET", "/v1/nodes")
        if not isinstance(data, list):
            return []
        return [NodeTelemetryPulse.model_validate(item) for item in data]

    async def create_pty_session(
        self,
        request: PtySessionRequest,
    ) -> PtySessionInfo:
        """Allocate an interactive PTY session for a running job on the remote controller.

        Args:
            request: PtySessionRequest payload describing terminal dimensions and command.

        Returns:
            Allocated PtySessionInfo.

        Raises:
            HexaqueueError: If the controller rejects or fails session creation.
        """
        payload = {
            "job_id": request.job_id,
            "session_id": request.session_id,
            "command": request.command,
            "user_id": request.user_id,
            "rows": request.rows,
            "cols": request.cols,
            "term_type": request.term_type,
        }
        data = await self._request(
            "POST", f"/v1/jobs/{request.job_id}/pty", json_body=payload
        )
        return PtySessionInfo.model_validate(data)

    async def create_bastion_session(self, node_id: str) -> PtySessionInfo:
        """Allocate an administrative bastion shell session on a compute worker node.

        Args:
            node_id: Target compute worker node identifier.

        Returns:
            Allocated PtySessionInfo for node shell attach.

        Raises:
            HexaqueueError: If the controller denies elevation or fails session allocation.
        """
        data = await self._request("POST", f"/v1/nodes/{node_id}/ssh")
        return PtySessionInfo.model_validate(data)

    async def evaluate_node_failures(
        self,
        timeout_unhealthy_seconds: float = 15.0,
        timeout_dead_seconds: float = 30.0,
    ) -> list[ComputeNodeProfile]:
        """Reject internal failure evaluation on remote controller clients.

        Args:
            timeout_unhealthy_seconds: Unused on remote clients.
            timeout_dead_seconds: Unused on remote clients.

        Raises:
            NotImplementedError: Always raised because failure evaluation is controller-internal.
        """
        raise NotImplementedError(
            "evaluate_node_failures is controller-internal and not exposed over HTTP",
        )

    async def list_dead_letters(self, limit: int = 50) -> list[DeadLetterRecord]:
        """Retrieve preserved dead-lettered job failure records from the remote controller.

        Args:
            limit: Maximum count of dead-letter records to return.

        Returns:
            List of DeadLetterRecord entries.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request("GET", "/v1/dlq")
        return DeadLetterQueueReport.model_validate(data).records[:limit]

    async def schedule_placement(
        self,
        job_id: str,
        collateral_hash_map: dict[str, str] | None = None,
    ) -> PlacementDecision:
        """Reject internal placement scheduling on remote controller clients.

        Args:
            job_id: Unused on remote clients.
            collateral_hash_map: Unused on remote clients.

        Raises:
            NotImplementedError: Always raised because scheduling is controller-internal.
        """
        raise NotImplementedError(
            "schedule_placement is controller-internal and not exposed over HTTP",
        )

    def create_memento(self) -> SchedulerMemento:
        """Reject internal memento capture on remote controller clients.

        Raises:
            NotImplementedError: Always raised because mementos are controller-internal.
        """
        raise NotImplementedError(
            "create_memento is controller-internal and not exposed over HTTP",
        )

    def restore_memento(self, memento: SchedulerMemento) -> None:
        """Reject internal memento restoration on remote controller clients.

        Args:
            memento: Unused on remote clients.

        Raises:
            NotImplementedError: Always raised because mementos are controller-internal.
        """
        raise NotImplementedError(
            "restore_memento is controller-internal and not exposed over HTTP",
        )

    async def simulate_placement(
        self,
        candidate_jobs: Sequence[JobSpec],
        collateral_hash_map: dict[str, str] | None = None,
    ) -> PlacementSimulationReport:
        """Simulate speculative placement on the remote controller.

        Args:
            candidate_jobs: List of JobSpec instances to simulate.
            collateral_hash_map: Optional collateral hash mapping.

        Returns:
            PlacementSimulationReport containing hypothetical placement outcomes.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request(
            "POST",
            "/v1/scheduler/simulate-placement",
            json_body={
                "candidate_jobs": [
                    job.model_dump(mode="json") for job in candidate_jobs
                ],
                "collateral_hash_map": collateral_hash_map,
            },
        )
        return PlacementSimulationReport.model_validate(data)

    async def rewind_run(
        self,
        run_id: str,
        target_job_ids: Sequence[str],
    ) -> DagRewindReport:
        """Rewind specified jobs and downstream dependents on the remote controller.

        Args:
            run_id: Pipeline run identifier.
            target_job_ids: Seed job IDs to reset and restart.

        Returns:
            DagRewindReport summarizing reset, re-enqueued, and unaffected tasks.

        Raises:
            HexaqueueError: If the controller request fails.
        """
        data = await self._request(
            "POST",
            f"/v1/runs/{run_id}/rewind",
            json_body={"target_job_ids": list(target_job_ids)},
        )
        return DagRewindReport.model_validate(data)


__all__ = [
    "HttpSchedulerControllerAdapter",
]
