"""Compute worker daemon agent for pull-based distributed test slice execution.

Notes/Architectural Intent:
    Implements the autonomous worker daemon running inside burst worker VMs/containers
    per ADR-008. The agent registers with the central coordinator, continuously maintains
    heartbeats to renew active leases, pulls test slices via long-polling, downloads CAS
    collateral via Pre-Authenticated Requests (PARs), executes pytest slices in isolation,
    uploads coverage artifacts directly to cloud object storage, and self-terminates
    upon sustained queue inactivity to guarantee scale-to-zero economics.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import os
import shutil
import sys
import tarfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from hexaqueue_core.domain.lease import (
    SliceLease,
    SliceReportPayload,
    WorkerRegistration,
)


@dataclass
class WorkerAgentConfig:
    """Configuration settings for the compute worker daemon agent.

    Args:
        controller_url: Base URL of the central controller's internal worker interface.
        join_token: Shared cluster authentication token (X-Hexaqueue-Join-Token).
        worker_id: Unique identifier for this worker instance.
        hostname: Optional hostname identifier.
        ip_address: Optional private IP address inside cluster VCN.
        ocpus: Allocated hardware OCPUs / vCPUs.
        memory_mb: Allocated RAM in megabytes.
        heartbeat_interval_seconds: Cadence for active lease heartbeat renewal.
        poll_timeout_seconds: Long-poll duration when requesting pending slices.
        idle_timeout_seconds: Inactivity period before worker initiates scale-to-zero shutdown.
        scratch_dir: Base directory for unpacking session collateral and workspaces.
    """

    controller_url: str = "http://localhost:8001"
    join_token: str | None = None
    worker_id: str = field(default_factory=lambda: f"worker-{uuid4().hex[:8]}")
    hostname: str | None = None
    ip_address: str | None = None
    ocpus: int = 1
    memory_mb: int = 6144
    heartbeat_interval_seconds: float = 15.0
    poll_timeout_seconds: float = 10.0
    idle_timeout_seconds: float = 180.0
    scratch_dir: Path | None = None

    @classmethod
    def from_env(cls) -> WorkerAgentConfig:
        """Construct configuration from environment variables.

        Returns:
            WorkerAgentConfig initialized from process environment.
        """
        controller_url = os.environ.get(
            "HEXAQUEUE_CONTROLLER_URL", "http://localhost:8001"
        ).rstrip("/")
        join_token = os.environ.get("HEXAQUEUE_JOIN_TOKEN")
        worker_id = os.environ.get("HEXAQUEUE_WORKER_ID") or f"worker-{uuid4().hex[:8]}"
        hostname = os.environ.get("HEXAQUEUE_WORKER_HOSTNAME")
        ip_address = os.environ.get("HEXAQUEUE_WORKER_IP") or os.environ.get(
            "HEXAQUEUE_IP_ADDRESS"
        )

        raw_ocpus = os.environ.get("HEXAQUEUE_WORKER_OCPUS")
        ocpus = (
            int(raw_ocpus)
            if raw_ocpus and raw_ocpus.isdigit()
            else (os.cpu_count() or 1)
        )

        raw_mem = os.environ.get("HEXAQUEUE_WORKER_MEMORY_MB")
        memory_mb = int(raw_mem) if raw_mem and raw_mem.isdigit() else 6144

        raw_idle = os.environ.get("HEXAQUEUE_AGENT_IDLE_TIMEOUT")
        idle_timeout = float(raw_idle) if raw_idle else 180.0

        raw_scratch = os.environ.get("HEXAQUEUE_AGENT_SCRATCH_DIR")
        scratch_dir = Path(raw_scratch) if raw_scratch else None

        return cls(
            controller_url=controller_url,
            join_token=join_token,
            worker_id=worker_id,
            hostname=hostname,
            ip_address=ip_address,
            ocpus=max(1, ocpus),
            memory_mb=max(512, memory_mb),
            idle_timeout_seconds=idle_timeout,
            scratch_dir=scratch_dir,
        )


class WorkerAgent:
    """Autonomous pull agent executing distributed test slices on compute nodes.

    Args:
        config: Optional WorkerAgentConfig configuration instance.
        client: Optional httpx.AsyncClient instance for testing or connection pooling.

    Notes/Architectural Intent:
        Communicates with the central SliceLeaseCoordinator via internal HTTP API (port 8001).
        Decoupled from controller implementation details; requires only standard HTTP REST
        and Object Storage Pre-Authenticated Requests (PARs).
    """

    def __init__(
        self,
        config: WorkerAgentConfig | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config or WorkerAgentConfig.from_env()
        self._custom_client = client
        self._active_leases: set[str] = set()
        self._stop_event = asyncio.Event()

    def _headers(self) -> dict[str, str]:
        """Construct HTTP headers with optional join token."""
        headers = {"content-type": "application/json"}
        if self.config.join_token:
            headers["x-hexaqueue-join-token"] = self.config.join_token
        return headers

    def stop(self) -> None:
        """Signal the worker agent to terminate the execution loop."""
        self._stop_event.set()

    async def register(self, client: httpx.AsyncClient) -> bool:
        """Register this worker node with the central cluster coordinator.

        Args:
            client: Active HTTP client.

        Returns:
            True if registration succeeded, False otherwise.
        """
        url = f"{self.config.controller_url}/worker/register"
        payload = WorkerRegistration(
            worker_id=self.config.worker_id,
            hostname=self.config.hostname,
            ip_address=self.config.ip_address,
            ocpus=self.config.ocpus,
            memory_mb=self.config.memory_mb,
        ).model_dump(mode="json")

        try:
            resp = await client.post(url, json=payload, headers=self._headers())
            return resp.status_code == 201
        except Exception:
            return False

    async def heartbeat(self, client: httpx.AsyncClient) -> bool:
        """Send pulse to renew active leases on the coordinator.

        Args:
            client: Active HTTP client.

        Returns:
            True if heartbeat was acknowledged, False otherwise.
        """
        url = f"{self.config.controller_url}/worker/{self.config.worker_id}/heartbeat"
        payload = {"active_lease_ids": list(self._active_leases)}
        try:
            resp = await client.post(url, json=payload, headers=self._headers())
            return resp.status_code == 200
        except Exception:
            return False

    async def lease_slice(self, client: httpx.AsyncClient) -> SliceLease | None:
        """Long-poll the coordinator to lease the next pending test slice.

        Args:
            client: Active HTTP client.

        Returns:
            Granted SliceLease, or None if queue is currently empty.
        """
        url = f"{self.config.controller_url}/worker/{self.config.worker_id}/lease"
        payload = {
            "available_ocpus": self.config.ocpus,
            "timeout_seconds": self.config.poll_timeout_seconds,
        }
        try:
            resp = await client.post(
                url,
                json=payload,
                headers=self._headers(),
                timeout=self.config.poll_timeout_seconds + 5.0,
            )
            if resp.status_code == 200 and resp.content:
                data = resp.json()
                return SliceLease.model_validate(data)
            return None
        except Exception:
            return None

    async def _unpack_collateral(
        self, download_url: str, target_workspace: Path
    ) -> bool:
        """Download and unpack collateral workspace archive via PAR.

        Args:
            download_url: Pre-authenticated GET URL.
            target_workspace: Target directory for unpacked code.

        Returns:
            True if extraction succeeded, False otherwise.
        """
        target_workspace.mkdir(parents=True, exist_ok=True)

        def _fetch() -> bool:
            try:
                with urllib.request.urlopen(  # noqa: S310
                    download_url, timeout=120
                ) as stream:
                    content = stream.read()
                with tarfile.open(fileobj=io.BytesIO(content), mode="r:*") as tar:
                    tar.extractall(path=target_workspace, filter="data")
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_fetch)

    async def _upload_coverage(self, upload_url: str, coverage_path: Path) -> bool:
        """Upload .coverage file to object storage via Pre-Authenticated PUT URL.

        Args:
            upload_url: Pre-authenticated PUT URL.
            coverage_path: Local path to .coverage database file.

        Returns:
            True if upload succeeded, False otherwise.
        """
        if not upload_url.startswith(("http://", "https://")):
            return False
        if not coverage_path.exists():
            return False

        payload_bytes = coverage_path.read_bytes()

        def _put() -> bool:
            try:
                req = urllib.request.Request(  # noqa: S310
                    upload_url,
                    data=payload_bytes,
                    headers={"Content-Type": "application/octet-stream"},
                    method="PUT",
                )
                with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
                    return int(resp.status) in (200, 201)
            except Exception:
                return False

        return await asyncio.to_thread(_put)

    async def _run_pytest_slice(
        self,
        nodeids: list[str],
        coverage_sources: list[str] | None,
        workspace: Path,
        start_time: float,
    ) -> tuple[int, list[dict[str, Any]], str, str]:
        """Execute pytest command on specified test nodeids.

        Args:
            nodeids: Target test identifiers.
            coverage_sources: Optional coverage packages.
            workspace: Working directory path.
            start_time: Monotonic start timestamp.

        Returns:
            Tuple of (exit_code, outcomes, stdout, stderr).
        """
        cmd = [sys.executable, "-m", "pytest", "-o", "junit_family=xunit2"]
        if coverage_sources:
            for src in coverage_sources:
                cmd.extend(["--cov", src])
        cmd.extend(nodeids)

        env = os.environ.copy()
        env["PYTHONPATH"] = str(workspace.resolve())

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        exit_code = proc.returncode or 0
        stdout_text = stdout_bytes.decode(errors="replace")
        stderr_text = stderr_bytes.decode(errors="replace")

        item_outcome = "passed" if exit_code == 0 else "failed"
        duration_per_item = max(
            0.001,
            (time.monotonic() - start_time) / max(1, len(nodeids)),
        )
        outcomes = [
            {
                "nodeid": nid,
                "outcome": item_outcome,
                "duration_seconds": round(duration_per_item, 3),
                "stdout": stdout_text if exit_code != 0 else None,
                "stderr": stderr_text if exit_code != 0 else None,
            }
            for nid in nodeids
        ]
        return exit_code, outcomes, stdout_text, stderr_text

    async def _handle_coverage_upload(
        self,
        task: Any,
        workspace: Path,
    ) -> str | None:
        """Upload coverage artifact if present and presigned URL configured.

        Args:
            task: Slice task descriptor.
            workspace: Workspace root directory.

        Returns:
            Uploaded object storage key if successful, None otherwise.
        """
        if not task.coverage_upload_url:
            return None
        cov_path = workspace / ".coverage"
        if not cov_path.exists():
            return None
        uploaded = await self._upload_coverage(task.coverage_upload_url, cov_path)
        if uploaded:
            return f"coverage/{task.session_id}/{task.slice_id}.coverage"
        return None

    async def execute_slice(
        self,
        lease: SliceLease,
        client: httpx.AsyncClient | None = None,
    ) -> SliceReportPayload:
        """Execute leased test slice in isolated scratch workspace.

        Args:
            lease: Active SliceLease assigned to this worker.
            client: Optional HTTP client.

        Returns:
            SliceReportPayload containing execution outcomes, timing, and coverage details.
        """
        task = lease.task
        base_dir = self.config.scratch_dir or (
            Path("/tmp/hexaqueue-worker") / self.config.worker_id
        )
        workspace = base_dir / task.session_id
        workspace.mkdir(parents=True, exist_ok=True)

        start_time = time.monotonic()
        outcomes: list[dict[str, Any]] = []
        exit_code = 0
        stdout_text = ""
        stderr_text = ""
        error_msg: str | None = None
        cov_key: str | None = None

        try:
            if task.collateral_download_url:
                extracted = await self._unpack_collateral(
                    task.collateral_download_url, workspace
                )
                if not extracted:
                    error_msg = f"Failed to download or extract collateral from {task.collateral_download_url}"
                    exit_code = 1

            if exit_code == 0 and task.test_nodeids:
                (
                    exit_code,
                    outcomes,
                    stdout_text,
                    stderr_text,
                ) = await self._run_pytest_slice(
                    task.test_nodeids,
                    task.coverage_sources,
                    workspace,
                    start_time,
                )

            cov_key = await self._handle_coverage_upload(task, workspace)

        except Exception as exc:
            exit_code = 1
            error_msg = str(exc)

        duration = max(0.001, round(time.monotonic() - start_time, 3))
        return SliceReportPayload(
            lease_id=lease.lease_id,
            slice_id=task.slice_id,
            worker_id=self.config.worker_id,
            exit_code=exit_code,
            duration_seconds=duration,
            outcomes=outcomes,
            coverage_object_key=cov_key,
            stdout=stdout_text[:4000] if stdout_text else None,
            stderr=stderr_text[:4000] if stderr_text else None,
            error_message=error_msg,
        )

    async def report_slice(
        self, client: httpx.AsyncClient, report: SliceReportPayload
    ) -> bool:
        """Report completed slice outcomes to the central cluster coordinator.

        Args:
            client: Active HTTP client.
            report: SliceReportPayload instance.

        Returns:
            True if report was accepted, False otherwise.
        """
        url = f"{self.config.controller_url}/worker/{self.config.worker_id}/report"
        try:
            resp = await client.post(
                url,
                json=report.model_dump(mode="json"),
                headers=self._headers(),
            )
            return resp.status_code == 200
        except Exception:
            return False

    async def run_step(self, client: httpx.AsyncClient) -> bool:
        """Execute one pull-lease-run-report cycle.

        Args:
            client: Active HTTP client.

        Returns:
            True if a task was leased and processed, False if queue was empty.
        """
        lease = await self.lease_slice(client)
        if lease is None:
            return False

        self._active_leases.add(lease.lease_id)
        try:
            report = await self.execute_slice(lease, client)
            await self.report_slice(client, report)
            return True
        finally:
            self._active_leases.discard(lease.lease_id)

    async def _run_heartbeat_loop(self, client: httpx.AsyncClient) -> None:
        """Periodic heartbeat sender running in background task.

        Args:
            client: Active HTTP client.
        """
        while not self._stop_event.is_set():
            await asyncio.sleep(self.config.heartbeat_interval_seconds)
            if self._stop_event.is_set():
                break
            await self.heartbeat(client)

    def _cleanup_agent_scratch(self) -> None:
        """Remove ephemeral scratch directories allocated by this agent."""
        base_dir = self.config.scratch_dir or (
            Path("/tmp/hexaqueue-worker") / self.config.worker_id
        )
        if base_dir.exists():
            shutil.rmtree(base_dir, ignore_errors=True)

    async def run(self) -> None:
        """Execute worker agent daemon lifecycle until idle timeout or stop signal."""
        client = self._custom_client or httpx.AsyncClient()
        consecutive_idle_seconds = 0.0
        heartbeat_task = None
        try:
            registered = await self.register(client)
            if not registered:
                return

            heartbeat_task = asyncio.create_task(self._run_heartbeat_loop(client))

            while not self._stop_event.is_set():
                processed = await self.run_step(client)
                consecutive_idle_seconds = (
                    0.0
                    if processed
                    else (consecutive_idle_seconds + self.config.poll_timeout_seconds)
                )
                if (
                    self.config.idle_timeout_seconds > 0.0
                    and consecutive_idle_seconds >= self.config.idle_timeout_seconds
                ):
                    break
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task

            self._cleanup_agent_scratch()

            if self._custom_client is None:
                await client.aclose()


def main() -> None:
    """Execute autonomous worker agent lifecycle from process environment.

    Notes/Architectural Intent:
        Standard entrypoint for execution via `python -m hexaqueue_worker.adapters.agent`
        or systemd background service inside burst worker VMs.
    """
    config = WorkerAgentConfig.from_env()
    agent = WorkerAgent(config=config)
    asyncio.run(agent.run())


if __name__ == "__main__":
    main()


__all__ = [
    "main",
    "WorkerAgent",
    "WorkerAgentConfig",
]
