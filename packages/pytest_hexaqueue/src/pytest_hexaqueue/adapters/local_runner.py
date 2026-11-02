"""Local subprocess test slice runner adapter.

Notes/Architectural Intent:
    Executes partitioned test slices locally via isolated pytest subprocesses,
    enabling hybrid concurrency topologies alongside remote Hexaqueue clusters
    and hermetic offline test execution.
"""

import asyncio
import base64
import os
import sys
import time
from pathlib import Path

from pytest_hexaqueue.domain.outcome import (
    SliceOutcomeReport,
    TestOutcomeItem,
)
from pytest_hexaqueue.domain.slice import TestSliceSpec


class LocalSliceRunner:
    """Executes test slice specifications locally in dedicated subprocesses.

    Args:
        concurrency: Maximum number of concurrent subprocesses to execute simultaneously,
            or 'auto' to match detected CPU cores.

    Notes/Architectural Intent:
        Guarantees process isolation across local slices, honoring monorepo import-mode
        and namespace traversal options without cross-test state leakage.
    """

    def __init__(self, concurrency: int | str = 4) -> None:
        if isinstance(concurrency, str) and concurrency.strip().casefold() == "auto":
            try:
                from hexaqual.domain.governance import resolve_parallelism

                self.concurrency = resolve_parallelism("auto")
            except (ImportError, ModuleNotFoundError):
                total_cores = os.cpu_count() or 1
                self.concurrency = max(1, total_cores - 2)
        else:
            self.concurrency = max(1, int(concurrency))
        self._semaphore = asyncio.Semaphore(self.concurrency)

    async def execute_slice(
        self,
        slice_spec: TestSliceSpec,
        coverage_sources: list[str] | None = None,
    ) -> SliceOutcomeReport:
        """Execute a single test slice in an isolated subprocess.

        Args:
            slice_spec: Specification detailing slice index, ID, and assigned test nodeids.
            coverage_sources: Optional list of package source paths for coverage tracking.

        Returns:
            SliceOutcomeReport detailing execution duration and per-item test outcomes.

        Raises:
            None.
        """
        if not slice_spec.test_nodeids:
            return SliceOutcomeReport(
                slice_id=slice_spec.slice_id,
                slice_index=slice_spec.slice_index,
                worker_id=f"worker-local-{slice_spec.slice_index}",
                provider="LOCAL",
                is_free_tier=True,
                outcomes=[],
                duration_seconds=0.0,
            )

        cov_flags: list[str] = []
        if coverage_sources:
            for src in coverage_sources:
                cov_flags.append(f"--cov={src}")
            cov_flags.extend(["--cov-report=", "--cov-fail-under=0"])

        cov_file = f".coverage.hq.{slice_spec.slice_id}"
        env = dict(os.environ)
        env.pop("HEXAQUEUE_CSP_PROVIDER", None)
        if coverage_sources:
            env["COVERAGE_FILE"] = cov_file

        cmd = [
            sys.executable,
            "-m",
            "pytest",
            *slice_spec.test_nodeids,
            "-o",
            "addopts=",
            "-o",
            "consider_namespace_packages=true",
            "-p",
            "no:cacheprovider",
            "--tb=short",
            "-q",
            *cov_flags,
        ]

        async with self._semaphore:
            start_time = time.monotonic()
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            slice_duration = max(0.001, time.monotonic() - start_time)
            exit_code = proc.returncode

        default_outcome = "passed" if exit_code == 0 else "failed"
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        per_item_dur = slice_duration / max(1, len(slice_spec.test_nodeids))
        outcomes = [
            TestOutcomeItem(
                nodeid=nid,
                outcome=default_outcome,
                duration_seconds=round(per_item_dur, 3),
                stdout=stdout_text if exit_code != 0 else None,
                stderr=stderr_text if exit_code != 0 else None,
            )
            for nid in slice_spec.test_nodeids
        ]

        cov_data: dict[str, str] | None = None
        if coverage_sources:
            cov_path = Path(cov_file)
            if cov_path.exists():
                file_bytes = cov_path.read_bytes()
                cov_data = {
                    "sqlite_b64": base64.b64encode(file_bytes).decode("ascii"),
                }

        return SliceOutcomeReport(
            slice_id=slice_spec.slice_id,
            slice_index=slice_spec.slice_index,
            worker_id=f"worker-local-{slice_spec.slice_index}",
            provider="LOCAL",
            is_free_tier=True,
            coverage_data=cov_data,
            outcomes=outcomes,
            duration_seconds=round(slice_duration, 3),
        )


__all__ = [
    "LocalSliceRunner",
]
