"""Unit tests for LocalSliceRunner adapter."""

import tempfile
import uuid
from pathlib import Path

import pytest
from pytest_hexaqueue.adapters.local_runner import LocalSliceRunner
from pytest_hexaqueue.domain.slice import TestSliceSpec


@pytest.mark.asyncio
async def test_local_slice_runner_empty_nodeids() -> None:
    """Verify execution of an empty slice returns an empty outcome report immediately."""
    runner = LocalSliceRunner(concurrency=2)
    spec = TestSliceSpec(
        slice_id="slice-empty",
        slice_index=0,
        total_slices=4,
        test_nodeids=[],
    )
    report = await runner.execute_slice(spec)
    slice_id = report.slice_id
    assert slice_id == "slice-empty"
    outcomes = report.outcomes
    assert len(outcomes) == 0
    passed = report.passed_count
    assert passed == 0
    provider = report.provider
    assert provider == "LOCAL"


@pytest.mark.asyncio
async def test_local_slice_runner_successful_execution() -> None:
    """Verify execution of passing tests generates passing outcomes."""
    runner = LocalSliceRunner(concurrency=1)
    spec = TestSliceSpec(
        slice_id=str(uuid.uuid4()),
        slice_index=1,
        total_slices=4,
        test_nodeids=[
            "packages/pytest_hexaqueue/tests/unit/domain/test_outcome.py::test_test_outcome_item"
        ],
    )
    report = await runner.execute_slice(spec)
    passed = report.passed_count
    assert passed == 1
    failed = report.failed_count
    assert failed == 0
    worker_id = report.worker_id
    assert worker_id is not None
    assert "worker-local-1" in worker_id
    dur = report.duration_seconds
    assert dur > 0.0


@pytest.mark.asyncio
async def test_local_slice_runner_failed_execution() -> None:
    """Verify execution of failing tests captures failures and logs."""
    runner = LocalSliceRunner(concurrency=2)
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test_dummy_failure.py"
        test_file.write_text("def test_fail(): assert False\n")

        spec = TestSliceSpec(
            slice_id="slice-fail",
            slice_index=2,
            total_slices=4,
            test_nodeids=[f"{test_file}::test_fail"],
        )
        report = await runner.execute_slice(spec)
        failed = report.failed_count
        assert failed == 1
        outcomes = report.outcomes
        assert outcomes[0].outcome == "failed"
        stderr = outcomes[0].stderr or outcomes[0].stdout
        assert stderr is not None


@pytest.mark.asyncio
async def test_local_slice_runner_with_coverage() -> None:
    """Verify coverage data generation when coverage_sources are specified."""
    runner = LocalSliceRunner(concurrency=2)
    spec = TestSliceSpec(
        slice_id=f"cov-{uuid.uuid4().hex[:6]}",
        slice_index=3,
        total_slices=4,
        test_nodeids=[
            "packages/pytest_hexaqueue/tests/unit/domain/test_outcome.py::test_test_outcome_item"
        ],
    )
    report = await runner.execute_slice(
        spec, coverage_sources=["pytest_hexaqueue.domain.outcome"]
    )
    passed = report.passed_count
    assert passed == 1
    cov_data = report.coverage_data
    if cov_data is not None:
        assert "sqlite_b64" in cov_data


def test_local_slice_runner_concurrency_auto() -> None:
    """Verify LocalSliceRunner initializes concurrency with auto detection."""
    runner = LocalSliceRunner(concurrency="auto")
    conc = runner.concurrency
    assert conc >= 1
