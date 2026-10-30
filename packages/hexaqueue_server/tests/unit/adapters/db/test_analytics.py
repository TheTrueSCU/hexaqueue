"""Unit tests for ColumnarAnalyticsAdapter zero-copy projections."""

import io
from datetime import UTC, datetime, timedelta

import polars as pl
import pytest

from hexaqueue_core.domain.budget import BudgetReservation, ReservationState
from hexaqueue_core.domain.cqrs import (
    BudgetReportResponse,
    ClusterMetricsReport,
    GetBudgetReportQuery,
    GetClusterMetricsQuery,
)
from hexaqueue_core.domain.job import JobSpec, JobStatus
from hexaqueue_core.domain.lifecycle import JobState, TerminalOutcome
from hexaqueue_core.domain.retry import DeadLetterRecord
from hexaqueue_core.domain.telemetry import GpuTelemetry
from hexaqueue_server.adapters.db.analytics import ColumnarAnalyticsAdapter
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse


@pytest.fixture
def sample_reservations() -> list[BudgetReservation]:
    """Fixture providing sample historical budget reservations."""
    now = datetime.now(UTC)
    return [
        BudgetReservation(
            reservation_id="res-1",
            tenant_id="tenant-alice",
            job_id="job-1",
            held_credits=120.0,
            state=ReservationState.SETTLED,
            created_at=now - timedelta(hours=2),
        ),
        BudgetReservation(
            reservation_id="res-2",
            tenant_id="tenant-alice",
            job_id="job-2",
            held_credits=80.0,
            state=ReservationState.SETTLED,
            created_at=now - timedelta(hours=4),
        ),
        BudgetReservation(
            reservation_id="res-3",
            tenant_id="tenant-bob",
            job_id="job-3",
            held_credits=50.0,
            state=ReservationState.ACTIVE,
            created_at=now - timedelta(hours=1),
        ),
    ]


@pytest.fixture
def sample_nodes() -> list[NodeTelemetryPulse]:
    """Fixture providing sample worker node telemetry pulses."""
    return [
        NodeTelemetryPulse(
            worker_id="node-gpu-01",
            cpu_utilization_pct=45.0,
            memory_total_mb=32768,
            memory_used_mb=16384,
            scratch_total_mb=100000,
            scratch_used_mb=20000,
            active_jobs=2,
            gpu_metrics=[
                GpuTelemetry(
                    index=0,
                    model="NVIDIA A100",
                    utilization_pct=85.0,
                    vram_used_mb=32000,
                    vram_total_mb=81920,
                    temperature_c=62.0,
                    power_w=280.0,
                ),
                GpuTelemetry(
                    index=1,
                    model="NVIDIA A100",
                    utilization_pct=0.0,  # Idle
                    vram_used_mb=0,
                    vram_total_mb=81920,
                    temperature_c=35.0,
                    power_w=45.0,
                ),
            ],
        ),
        NodeTelemetryPulse(
            worker_id="node-cpu-02",
            cpu_utilization_pct=90.0,
            memory_total_mb=65536,
            memory_used_mb=32768,
            scratch_total_mb=100000,
            scratch_used_mb=10000,
            active_jobs=4,
            gpu_metrics=[],
        ),
    ]


@pytest.fixture
def sample_jobs() -> list[JobSpec]:
    """Fixture providing sample evaluated job records."""
    now = datetime.now(UTC)
    return [
        JobSpec(
            id="job-ok-1",
            run_id="run-1",
            name="ok-1",
            command="echo 1",
            status=JobStatus(
                state=JobState.DONE,
                outcome=TerminalOutcome.COMPLETED,
            ),
            created_at=now,
            updated_at=now,
        ),
        JobSpec(
            id="job-fail-1",
            run_id="run-1",
            name="fail-oom",
            command="oom",
            status=JobStatus(
                state=JobState.DONE,
                outcome=TerminalOutcome.FAILED,
                reason="OUT_OF_MEMORY",
            ),
            created_at=now,
            updated_at=now,
        ),
        JobSpec(
            id="job-fail-2",
            run_id="run-1",
            name="fail-timeout",
            command="sleep",
            status=JobStatus(
                state=JobState.DONE,
                outcome=TerminalOutcome.FAILED,
                reason="TIMEOUT",
            ),
            created_at=now,
            updated_at=now,
        ),
    ]


@pytest.fixture
def sample_dlq() -> list[DeadLetterRecord]:
    """Fixture providing sample DLQ retry failure records."""
    now = datetime.now(UTC)
    return [
        DeadLetterRecord(
            job_id="job-dlq-1",
            run_id="run-1",
            failure_reason="NonRecoverableError: Bad command line",
            retry_count=3,
            timestamp=now - timedelta(minutes=30),
        ),
        DeadLetterRecord(
            job_id="job-dlq-2",
            run_id="run-1",
            failure_reason="NonRecoverableError: Bad command line",
            retry_count=3,
            timestamp=now - timedelta(minutes=15),
        ),
    ]


def test_project_budget_report_json(
    sample_reservations: list[BudgetReservation],
) -> None:
    """Verify JSON projection of aggregated budget report."""
    adapter = ColumnarAnalyticsAdapter()
    query = GetBudgetReportQuery(window_hours=24, format="json")
    report = adapter.project_budget_report(query, sample_reservations)

    assert isinstance(report, BudgetReportResponse)
    assert report.total_spend_credits == 250.0
    assert report.total_reservations == 3
    assert report.burn_rate_credits_per_hour == round(250.0 / 24, 4)

    res_tenant_count = len(report.by_tenant)
    assert res_tenant_count == 2
    assert report.by_tenant[0]["tenant_id"] == "tenant-alice"
    assert report.by_tenant[0]["total_credits"] == 200.0


def test_project_budget_report_tenant_filter(
    sample_reservations: list[BudgetReservation],
) -> None:
    """Verify tenant-scoped budget projection."""
    adapter = ColumnarAnalyticsAdapter()
    query = GetBudgetReportQuery(tenant_id="tenant-bob", window_hours=24, format="json")
    report = adapter.project_budget_report(query, sample_reservations)

    assert isinstance(report, BudgetReportResponse)
    assert report.total_spend_credits == 50.0
    assert report.total_reservations == 1
    res_tenant_count = len(report.by_tenant)
    assert res_tenant_count == 1
    assert report.by_tenant[0]["tenant_id"] == "tenant-bob"


def test_project_budget_report_columnar_round_trip(
    sample_reservations: list[BudgetReservation],
) -> None:
    """Verify zero-copy Parquet, Arrow IPC, and CSV binary export round-trips."""
    adapter = ColumnarAnalyticsAdapter()

    # Parquet
    parquet_bytes = adapter.project_budget_report(
        GetBudgetReportQuery(format="parquet"), sample_reservations
    )
    assert isinstance(parquet_bytes, bytes)
    df_parquet = pl.read_parquet(io.BytesIO(parquet_bytes))
    assert df_parquet.height == 3
    assert "held_credits" in df_parquet.columns

    # Arrow IPC
    ipc_bytes = adapter.project_budget_report(
        GetBudgetReportQuery(format="arrow_ipc"), sample_reservations
    )
    assert isinstance(ipc_bytes, bytes)
    df_ipc = pl.read_ipc(io.BytesIO(ipc_bytes))
    assert df_ipc.height == 3

    # CSV
    csv_bytes = adapter.project_budget_report(
        GetBudgetReportQuery(format="csv"), sample_reservations
    )
    assert isinstance(csv_bytes, bytes)
    df_csv = pl.read_csv(io.BytesIO(csv_bytes))
    assert df_csv.height == 3


def test_project_budget_report_empty() -> None:
    """Verify budget report behavior when no reservations exist."""
    adapter = ColumnarAnalyticsAdapter()
    report = adapter.project_budget_report(
        GetBudgetReportQuery(window_hours=12, format="json"), []
    )
    assert isinstance(report, BudgetReportResponse)
    assert report.total_spend_credits == 0.0
    assert report.total_reservations == 0
    assert report.by_tenant == []

    # Non-json empty export
    empty_parquet = adapter.project_budget_report(
        GetBudgetReportQuery(format="parquet"), []
    )
    assert isinstance(empty_parquet, bytes)
    df = pl.read_parquet(io.BytesIO(empty_parquet))
    assert df.height == 0


def test_project_cluster_metrics_json(
    sample_nodes: list[NodeTelemetryPulse],
    sample_jobs: list[JobSpec],
    sample_dlq: list[DeadLetterRecord],
) -> None:
    """Verify JSON projection of cluster utilization percentiles and error rates."""
    adapter = ColumnarAnalyticsAdapter()
    query = GetClusterMetricsQuery(window_hours=24, format="json")
    report = adapter.project_cluster_metrics(
        query, nodes=sample_nodes, jobs=sample_jobs, dlq_records=sample_dlq
    )

    assert isinstance(report, ClusterMetricsReport)
    assert report.node_utilization_p50 > 0.0
    assert report.gpu_idle_pct == 50.0  # 1 of 2 GPUs idle
    assert report.total_jobs_evaluated == 3
    assert "OUT_OF_MEMORY" in report.error_rate_by_classification
    assert "TIMEOUT" in report.error_rate_by_classification

    res_dlq_count = len(report.dlq_trends)
    assert res_dlq_count == 1
    assert report.dlq_trends[0]["occurrences"] == 2


def test_project_cluster_metrics_columnar_export(
    sample_nodes: list[NodeTelemetryPulse],
    sample_jobs: list[JobSpec],
) -> None:
    """Verify binary columnar serialization for cluster metrics."""
    adapter = ColumnarAnalyticsAdapter()
    parquet_bytes = adapter.project_cluster_metrics(
        GetClusterMetricsQuery(format="parquet"),
        nodes=sample_nodes,
        jobs=sample_jobs,
    )
    assert isinstance(parquet_bytes, bytes)
    df = pl.read_parquet(io.BytesIO(parquet_bytes))
    assert df.height == 1
    assert "node_utilization_p50" in df.columns
    assert "gpu_idle_pct" in df.columns
