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
import base64
import contextlib
import io
import os
import shlex
import shutil
import signal
import sys
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from hexaqueue_core.domain.lease import (
    SliceLease,
    SliceReportPayload,
    WorkerRegistration,
)
from hexaqueue_core.ports.logging import LogChunk

_WORKER_INTERNAL_ENV_KEYS: tuple[str, ...] = (
    "HEXAQUEUE_CONTROLLER_URL",
    "HEXAQUEUE_URL",
    "HEXAQUEUE_JOIN_TOKEN",
    "HEXAQUEUE_ADMIN_TOKEN",
    "HEXAQUEUE_WORKER_ID",
    "HEXAQUEUE_WORKER_HOSTNAME",
    "HEXAQUEUE_WORKER_IP",
    "HEXAQUEUE_WORKER_OCPUS",
    "HEXAQUEUE_WORKER_MEMORY_MB",
    "HEXAQUEUE_AGENT_IDLE_TIMEOUT",
    "HEXAQUEUE_AGENT_SCRATCH_DIR",
    "VIRTUAL_ENV",
    "UV_RUN_RECURSION_DEPTH",
    "UV_PROJECT_ENVIRONMENT",
    "UV_PYTHON",
    "PYTHONHOME",
)
_SHELL_METACHARACTERS: tuple[str, ...] = (
    "&&",
    "||",
    "|",
    ";",
    ">",
    "<",
    "$",
    "`",
    "\n",
)


def _find_uv_binary() -> str | None:
    """Locate the ``uv`` CLI executable across PATH and standard install directories.

    Returns:
        Absolute executable path to ``uv`` when available, else ``None``.

    Notes/Architectural Intent:
        Worker daemons started under minimal ``systemd`` environments inherit a
        restricted ``PATH`` that omits user-local install directories such as
        ``~/.local/bin`` or ``~/.cargo/bin``. Checking standard candidate paths
        ensures ``uv run --project`` reliably syncs workspace dependencies rather
        than falling back to the daemon's own virtual environment.
    """
    if path_uv := shutil.which("uv"):
        return path_uv

    home = Path.home()
    candidates = (
        home / ".local" / "bin" / "uv",
        home / ".cargo" / "bin" / "uv",
        Path("/usr/local/bin/uv"),
        Path("/root/.local/bin/uv"),
    )
    for candidate in candidates:
        with contextlib.suppress(OSError):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _is_path_in_venv(entry: str, venv_root: Path) -> bool:
    """Return True when a PATH entry resolves inside ``venv_root``.

    Args:
        entry: Candidate ``PATH`` directory entry.
        venv_root: Resolved worker virtualenv root directory.

    Returns:
        ``True`` if ``entry`` resolves inside ``venv_root``, otherwise ``False``.

    Notes/Architectural Intent:
        Uses ``contextlib.suppress(OSError)`` so broken symlinks or unresolvable
        ``PATH`` segments safely return ``False`` instead of raising or leaving
        an empty ``except`` block.
    """
    with contextlib.suppress(OSError):
        return Path(entry).resolve().is_relative_to(venv_root)
    return False


def _sanitize_task_path(
    raw_path: str,
    worker_venv: str | None,
    uv_bin: str | None,
) -> str:
    """Strip the worker daemon virtualenv from ``PATH`` and expose ``uv``.

    Args:
        raw_path: Original ``PATH`` string inherited from the worker process.
        worker_venv: Active worker ``VIRTUAL_ENV`` path, if any.
        uv_bin: Resolved ``uv`` binary path, if found.

    Returns:
        Sanitized ``PATH`` string safe for isolated workspace task execution.

    Notes/Architectural Intent:
        Removes entries inside the worker agent's own virtualenv so child
        ``pytest`` or ``uv`` processes resolve executables from the target
        workspace instead of the daemon's environment, while appending the
        parent directory of ``uv_bin`` when missing.
    """
    venv_root: Path | None = None
    if worker_venv:
        with contextlib.suppress(OSError):
            venv_root = Path(worker_venv).resolve()

    filtered: list[str] = []
    for entry in raw_path.split(os.pathsep):
        if not entry:
            continue
        if venv_root is not None and _is_path_in_venv(entry, venv_root):
            continue
        filtered.append(entry)

    if uv_bin:
        uv_dir = str(Path(uv_bin).parent)
        if uv_dir not in filtered:
            filtered.append(uv_dir)

    return os.pathsep.join(filtered)


def _build_task_env(
    workspace: Path,
    task_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build sanitized subprocess environment for leased worker tasks.

    Args:
        workspace: Base workspace directory for the leased task.
        task_env: Optional explicit task environment overrides. When provided,
            ``PYTHONUNBUFFERED`` is enabled and explicit keys take precedence.

    Returns:
        Isolated environment dictionary safe to pass to child task processes.

    Notes/Architectural Intent:
        Strips worker daemon control-plane variables (such as
        ``HEXAQUEUE_CONTROLLER_URL`` and ``HEXAQUEUE_JOIN_TOKEN``) and virtual
        environment variables inherited from the agent's systemd service so
        hermetic unit tests and unprivileged tasks cannot unintentionally target
        the live cluster coordinator or resolve the daemon virtualenv.
    """
    env = os.environ.copy()
    worker_venv = env.get("VIRTUAL_ENV")
    for key in _WORKER_INTERNAL_ENV_KEYS:
        env.pop(key, None)

    env["PATH"] = _sanitize_task_path(
        env.get("PATH", ""),
        worker_venv,
        _find_uv_binary(),
    )

    src_paths: list[str] = [
        str(p) for p in sorted((workspace / "packages").glob("*/src"))
    ]
    if (workspace / "src").is_dir():
        src_paths.append(str(workspace / "src"))
    src_paths.append(str(workspace.resolve()))
    env["PYTHONPATH"] = os.pathsep.join(src_paths)

    if task_env is not None:
        env["PYTHONUNBUFFERED"] = "1"
        env.update(task_env)
        env.pop("HEXAQUEUE_CWD", None)
    return env


def _uv_project_cmd_prefix(workspace: Path) -> list[str] | None:
    """Return ``uv run --project ...`` prefix syncing all workspace packages if present.

    Args:
        workspace: Base workspace directory inspected for ``pyproject.toml`` or ``uv.lock``.

    Returns:
        Command prefix list when ``uv`` and a project manifest exist, else ``None``.

    Notes/Architectural Intent:
        Multi-package uv workspaces (e.g. Hexastack) declare package dependencies in
        member ``pyproject.toml`` manifests under ``packages/*``. Passing
        ``--all-packages --all-extras --all-groups`` ensures remote worker slices
        provision member dependencies on first execution while staying a clean no-op
        for single-package repositories.
    """
    uv_bin = _find_uv_binary()
    has_uv_project = (workspace / "pyproject.toml").is_file() or (
        workspace / "uv.lock"
    ).is_file()
    if uv_bin and has_uv_project:
        return [
            uv_bin,
            "run",
            "--project",
            str(workspace),
            "--all-packages",
            "--all-extras",
            "--all-groups",
        ]
    return None


def _resolve_command_invocation(
    command: str,
    args: list[str],
    workspace: Path,
) -> tuple[bool, list[str] | str]:
    """Resolve how a batch command task should be invoked in a workspace.

    Args:
        command: Executable or single-string command line specified by the job.
        args: Explicit argument list (empty when job encoded args inside ``command``).
        workspace: Base workspace directory for ``uv run --project`` detection.

    Returns:
        Tuple of ``(use_shell, command_spec)`` where ``use_shell=True`` returns
        a shell command string and ``use_shell=False`` returns an ``argv`` list.

    Notes/Architectural Intent:
        Mirrors ``LocalSubprocessExecutionRuntimeAdapter`` semantics for jobs
        submitted with single-string commands (e.g. ``"echo 'Hello World'"`` or
        shell pipelines) while keeping explicit ``command`` + ``args`` tuples
        direct via ``create_subprocess_exec``.
    """
    if not args and any(tok in command for tok in _SHELL_METACHARACTERS):
        return True, command

    if not args and any(ch.isspace() for ch in command):
        try:
            tokens = shlex.split(command)
        except ValueError:
            return True, command
        if tokens:
            executable, resolved_args = tokens[0], tokens[1:]
        else:
            executable, resolved_args = command, []
    else:
        executable, resolved_args = command, list(args)

    uv_prefix = _uv_project_cmd_prefix(workspace)
    if (
        uv_prefix is not None
        and not Path(executable).is_absolute()
        and not executable.startswith("uv")
    ):
        return False, [*uv_prefix, executable, *resolved_args]
    return False, [executable, *resolved_args]


async def _terminate_process_group(
    proc: asyncio.subprocess.Process,
    grace_seconds: float = 5.0,
) -> None:
    """Terminate an active worker subprocess and its entire process group cleanly.

    Args:
        proc: Subprocess handle spawned by the worker agent.
        grace_seconds: Grace period in seconds between SIGTERM and SIGKILL.

    Notes/Architectural Intent:
        Terminates detached POSIX process groups (``start_new_session=True``) so
        hung child ``pytest`` or ``pytest-xdist`` workers cannot survive lease
        cancellation or slice wall-clock timeouts as orphaned background processes.
    """
    if getattr(proc, "returncode", None) is not None:
        return
    pid = getattr(proc, "pid", None)
    use_pg = (
        os.name != "nt"
        and isinstance(pid, int)
        and pid > 0
        and hasattr(os, "killpg")
        and hasattr(os, "getpgid")
    )
    with contextlib.suppress(ProcessLookupError, OSError):
        if use_pg and pid is not None:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            proc.terminate()
    with contextlib.suppress(TimeoutError, ProcessLookupError, OSError):
        await asyncio.wait_for(proc.wait(), timeout=max(0.05, grace_seconds))
    if getattr(proc, "returncode", None) is not None:
        return
    with contextlib.suppress(ProcessLookupError, OSError):
        if use_pg and pid is not None:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        else:
            proc.kill()
    with contextlib.suppress(TimeoutError, ProcessLookupError, OSError):
        await asyncio.wait_for(proc.wait(), timeout=2.0)


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
        slice_timeout_seconds: Maximum wall-clock runtime per leased slice in seconds
            (``<= 0`` disables local enforcement).
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
    slice_timeout_seconds: float = 2400.0
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

        raw_slice_timeout = os.environ.get("HEXAQUEUE_SLICE_TIMEOUT_SECONDS")
        slice_timeout = 2400.0
        if raw_slice_timeout:
            with contextlib.suppress(ValueError):
                slice_timeout = float(raw_slice_timeout)

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
            slice_timeout_seconds=slice_timeout,
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
        self._active_procs: dict[str, asyncio.subprocess.Process] = {}
        self._cancelled_leases: set[str] = set()
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

    def _collect_host_telemetry(self) -> dict[str, Any]:
        """Collect lightweight live host CPU, load average, RAM, and scratch disk telemetry."""
        telemetry: dict[str, Any] = {}
        with contextlib.suppress(OSError):
            loads = os.getloadavg()
            telemetry["load_average"] = [
                round(loads[0], 2),
                round(loads[1], 2),
                round(loads[2], 2),
            ]
            cpu_count = max(1, os.cpu_count() or self.config.ocpus or 1)
            telemetry["cpu_utilization_pct"] = round(
                min(100.0, (loads[0] / cpu_count) * 100.0), 1
            )

        meminfo = Path("/proc/meminfo")
        if meminfo.is_file():
            with contextlib.suppress(OSError, ValueError):
                vals: dict[str, int] = {}
                for line in meminfo.read_text(encoding="utf-8").splitlines():
                    if line.startswith(("MemTotal:", "MemAvailable:")):
                        key, rest = line.split(":", 1)
                        vals[key] = int(rest.strip().split()[0])
                if "MemTotal" in vals:
                    total_mb = vals["MemTotal"] // 1024
                    avail_mb = vals.get("MemAvailable", 0) // 1024
                    telemetry["memory_total_mb"] = total_mb
                    telemetry["memory_used_mb"] = max(0, total_mb - avail_mb)

        with contextlib.suppress(OSError):
            scratch_path = self.config.scratch_dir or Path(tempfile.gettempdir())
            usage = shutil.disk_usage(scratch_path)
            telemetry["scratch_total_mb"] = usage.total // (1024 * 1024)
            telemetry["scratch_used_mb"] = usage.used // (1024 * 1024)
        return telemetry

    async def heartbeat(self, client: httpx.AsyncClient) -> bool:
        """Send pulse to renew active leases on the coordinator.

        Args:
            client: Active HTTP client.

        Returns:
            True if heartbeat was acknowledged, False otherwise.

        Notes/Architectural Intent:
            Self-heals after controller restarts (which reset in-memory worker
            registrations) by re-registering automatically on HTTP 404 and
            retrying the heartbeat once.
        """
        url = f"{self.config.controller_url}/worker/{self.config.worker_id}/heartbeat"
        payload: dict[str, Any] = {
            "active_lease_ids": list(self._active_leases),
            **self._collect_host_telemetry(),
        }
        try:
            resp = await client.post(url, json=payload, headers=self._headers())
            if resp.status_code == 404 and await self.register(client):
                resp = await client.post(url, json=payload, headers=self._headers())
            if resp.status_code != 200:
                return False
            await self._handle_heartbeat_cancellations(resp)
            return True
        except Exception:
            return False

    async def _handle_heartbeat_cancellations(self, resp: httpx.Response) -> None:
        """Terminate any active subprocess whose lease was cancelled on coordinator."""
        payload_data: Any = None
        with contextlib.suppress(Exception):
            payload_data = resp.json()
        if not isinstance(payload_data, dict):
            return
        cancelled_ids = payload_data.get("cancelled_lease_ids")
        if not isinstance(cancelled_ids, list):
            return
        for raw_lid in cancelled_ids:
            lid = str(raw_lid)
            self._cancelled_leases.add(lid)
            proc = self._active_procs.get(lid)
            if proc is not None:
                await _terminate_process_group(proc)

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

    async def _flush_log_chunks(
        self,
        client: httpx.AsyncClient | None,
        job_id: str | None,
        chunks: list[LogChunk],
    ) -> None:
        """Best-effort POST of incremental LogChunk batch to the central controller."""
        if client is None or not job_id or not chunks:
            return
        url = (
            f"{self.config.controller_url}/worker/{self.config.worker_id}/logs/{job_id}"
        )
        headers: dict[str, str] = {}
        if self.config.join_token:
            headers["X-Hexaqueue-Join-Token"] = self.config.join_token
        payload = [c.model_dump(mode="json") for c in chunks]
        with contextlib.suppress(Exception):
            await client.post(url, json=payload, headers=headers, timeout=5.0)

    async def _stream_process_output(
        self,
        proc: asyncio.subprocess.Process,
        job_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[int, str, str]:
        """Read subprocess stdout/stderr incrementally and flush live LogChunks."""
        stdout_parts: list[str] = []
        stderr_parts: list[str] = []
        pending: list[LogChunk] = []
        offset = 0
        last_flush = time.monotonic()
        flush_lock = asyncio.Lock()

        async def _flush_if_needed(force: bool = False) -> None:
            nonlocal last_flush
            async with flush_lock:
                now = time.monotonic()
                if pending and (force or len(pending) >= 20 or now - last_flush >= 1.0):
                    batch = list(pending)
                    pending.clear()
                    last_flush = now
                    await self._flush_log_chunks(client, job_id, batch)

        async def _pump(
            stream: asyncio.StreamReader | None,
            stream_name: str,
            sink: list[str],
        ) -> None:
            nonlocal offset
            if stream is None:
                return
            while True:
                line = await stream.readline()
                if not line or not isinstance(line, (bytes, bytearray)):
                    break
                text = line.decode(errors="replace")
                sink.append(text)
                if client is not None and job_id:
                    pending.append(
                        LogChunk(
                            job_id=job_id,
                            stream="stderr" if stream_name == "stderr" else "stdout",
                            content=text.rstrip("\n"),
                            offset=offset,
                            timestamp=datetime.now(UTC),
                        )
                    )
                    offset += 1
                    await _flush_if_needed(force=False)

        await asyncio.gather(
            _pump(proc.stdout, "stdout", stdout_parts),
            _pump(proc.stderr, "stderr", stderr_parts),
        )
        exit_code = await proc.wait()
        await _flush_if_needed(force=True)
        return exit_code or 0, "".join(stdout_parts), "".join(stderr_parts)

    async def _stream_with_lease_guard(
        self,
        proc: asyncio.subprocess.Process,
        *,
        lease_id: str | None = None,
        job_id: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> tuple[int, str, str]:
        """Run ``_stream_process_output`` with active lease tracking and wall-clock timeout."""
        if lease_id is not None:
            self._active_procs[lease_id] = proc
            if lease_id in self._cancelled_leases:
                await _terminate_process_group(proc)
        timeout_val = (
            self.config.slice_timeout_seconds
            if self.config.slice_timeout_seconds > 0.0
            else None
        )
        try:
            coro = self._stream_process_output(proc, job_id=job_id, client=client)
            if timeout_val is None:
                return await coro
            return await asyncio.wait_for(coro, timeout=timeout_val)
        except TimeoutError:
            await _terminate_process_group(proc)
            msg = f"Slice {job_id or lease_id or 'task'} exceeded worker timeout ({timeout_val:.1f}s)."
            return 124, "", msg
        finally:
            if lease_id is not None:
                self._active_procs.pop(lease_id, None)

    async def _run_pytest_slice(
        self,
        nodeids: list[str],
        coverage_sources: list[str] | None,
        workspace: Path,
        start_time: float,
        job_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        lease_id: str | None = None,
    ) -> tuple[int, list[dict[str, Any]], str, str]:
        """Execute pytest command on specified test nodeids.

        Args:
            nodeids: Target test identifiers.
            coverage_sources: Optional coverage packages.
            workspace: Working directory path.
            start_time: Monotonic start timestamp.
            job_id: Optional job/slice identifier for live log streaming.
            client: Optional async HTTP client for streaming incremental log chunks.
            lease_id: Optional active lease identifier for cancellation tracking.

        Returns:
            Tuple of (exit_code, outcomes, stdout, stderr).
        """
        uv_prefix = _uv_project_cmd_prefix(workspace)
        if uv_prefix is not None:
            cmd = [
                *uv_prefix,
                "pytest",
                "-o",
                "junit_family=xunit2",
                "-p",
                "no:hexaqueue",
                "--cov-fail-under=0",
                "--cov-report=",
            ]
        else:
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                "-o",
                "junit_family=xunit2",
                "-p",
                "no:hexaqueue",
                "--cov-fail-under=0",
                "--cov-report=",
            ]
        if coverage_sources:
            for src in coverage_sources:
                cmd.extend(["--cov", src])
        cmd.extend(nodeids)

        env = _build_task_env(workspace)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(workspace),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=(os.name != "nt"),
        )
        exit_code, stdout_text, stderr_text = await self._stream_with_lease_guard(
            proc, lease_id=lease_id, job_id=job_id, client=client
        )

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

    async def _run_command_task(
        self,
        command: str,
        args: list[str],
        task_env: dict[str, str],
        workspace: Path,
        relative_cwd: str | None,
        start_time: float,
        job_id: str | None = None,
        client: httpx.AsyncClient | None = None,
        lease_id: str | None = None,
    ) -> tuple[int, list[dict[str, Any]], str, str]:
        """Execute arbitrary command or batch task in workspace.

        Args:
            command: Executable command string or entrypoint.
            args: Command-line arguments.
            task_env: Task-specific environment variables.
            workspace: Base workspace root directory.
            relative_cwd: Optional working directory relative to workspace root.
            start_time: Monotonic start timestamp.
            job_id: Optional job/slice identifier for live log streaming.
            client: Optional async HTTP client for streaming incremental log chunks.
            lease_id: Optional active lease identifier for cancellation tracking.

        Returns:
            Tuple of (exit_code, outcomes, stdout, stderr).
        """
        cwd_path = (workspace / relative_cwd).resolve() if relative_cwd else workspace
        if not cwd_path.exists():
            cwd_path = workspace

        use_shell, resolved_cmd = _resolve_command_invocation(command, args, workspace)
        env = _build_task_env(workspace, task_env)

        if use_shell and isinstance(resolved_cmd, str):
            proc = await asyncio.create_subprocess_shell(
                resolved_cmd,
                cwd=str(cwd_path),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name != "nt"),
            )
        else:
            cmd_list = (
                resolved_cmd if isinstance(resolved_cmd, list) else [str(resolved_cmd)]
            )
            proc = await asyncio.create_subprocess_exec(
                *cmd_list,
                cwd=str(cwd_path),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name != "nt"),
            )
        exit_code, stdout_text, stderr_text = await self._stream_with_lease_guard(
            proc, lease_id=lease_id, job_id=job_id, client=client
        )

        item_outcome = "passed" if exit_code == 0 else "failed"
        duration = max(0.001, time.monotonic() - start_time)
        node_id = f"{command} {' '.join(args)}".strip()
        outcomes = [
            {
                "nodeid": node_id,
                "outcome": item_outcome,
                "duration_seconds": round(duration, 3),
                "stdout": stdout_text if exit_code != 0 else None,
                "stderr": stderr_text if exit_code != 0 else None,
            }
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
        inline_cov: dict[str, Any] | None = None

        try:
            if task.collateral_download_url:
                extracted = await self._unpack_collateral(
                    task.collateral_download_url, workspace
                )
                if not extracted:
                    error_msg = f"Failed to download or extract collateral from {task.collateral_download_url}"
                    exit_code = 1

            if exit_code == 0 and lease.lease_id not in self._cancelled_leases:
                if task.command:
                    (
                        exit_code,
                        outcomes,
                        stdout_text,
                        stderr_text,
                    ) = await self._run_command_task(
                        task.command,
                        task.args,
                        task.env,
                        workspace,
                        task.cwd,
                        start_time,
                        job_id=task.slice_id,
                        client=client,
                        lease_id=lease.lease_id,
                    )
                elif task.test_nodeids:
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
                        job_id=task.slice_id,
                        client=client,
                        lease_id=lease.lease_id,
                    )

            if lease.lease_id in self._cancelled_leases:
                exit_code = 130
                error_msg = f"Lease {lease.lease_id} cancelled by coordinator"

            cov_key = await self._handle_coverage_upload(task, workspace)
            cov_path = workspace / ".coverage"
            if cov_path.exists():
                cov_bytes = cov_path.read_bytes()
                inline_cov = {
                    "sqlite_b64": base64.b64encode(cov_bytes).decode("ascii"),
                    "workspace_root": str(workspace.resolve()),
                }

        except Exception as exc:
            exit_code = 1
            error_msg = str(exc)
        finally:
            self._cancelled_leases.discard(lease.lease_id)

        duration = max(0.001, round(time.monotonic() - start_time, 3))
        return SliceReportPayload(
            lease_id=lease.lease_id,
            slice_id=task.slice_id,
            worker_id=self.config.worker_id,
            coverage_data=inline_cov,
            coverage_object_key=cov_key,
            duration_seconds=duration,
            error_message=error_msg,
            exit_code=exit_code,
            outcomes=outcomes,
            stdout=stdout_text[:4000] if stdout_text else None,
            stderr=stderr_text[:4000] if stderr_text else None,
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
            try:
                report = await self.execute_slice(lease, client)
            except Exception as exc:
                report = SliceReportPayload(
                    lease_id=lease.lease_id,
                    slice_id=lease.task.slice_id,
                    worker_id=self.config.worker_id,
                    exit_code=1,
                    error_message=f"Worker execution error: {exc}",
                    duration_seconds=0.001,
                )
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
        """Execute worker agent daemon lifecycle until idle timeout or stop signal.

        Raises:
            RuntimeError: If initial registration with coordinator fails after retries.
        """
        client = self._custom_client or httpx.AsyncClient()
        consecutive_idle_seconds = 0.0
        heartbeat_task = None
        try:
            registered = False
            for _ in range(10):
                if self._stop_event.is_set():
                    return
                registered = await self.register(client)
                if registered:
                    break
                await asyncio.sleep(2.0)

            if not registered:
                raise RuntimeError(
                    f"Worker {self.config.worker_id} failed to register with coordinator "
                    f"at {self.config.controller_url} after 10 attempts"
                )

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
            for active_proc in list(self._active_procs.values()):
                with contextlib.suppress(Exception):
                    await _terminate_process_group(active_proc)
            self._active_procs.clear()

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
