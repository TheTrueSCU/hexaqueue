"""Zero-copy columnar telemetry and accounting projection adapter using Polars and Apache Arrow.

Notes/Architectural Intent:
    Implements high-speed vectorized analytical projections over historical
    jobs, budget reservations, and cluster hardware telemetry. Supports
    zero-copy Apache Arrow table streaming, Polars DataFrames, and direct binary
    serializations (Parquet, Arrow IPC, CSV) bypassing ORM iteration overhead.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta
from typing import Any

import polars as pl
from hexastack_db.adapters.analytics import PolarsColumnarAdapter

from hexaqueue_core.domain.budget import BudgetReservation
from hexaqueue_core.domain.cqrs import (
    BudgetReportResponse,
    ClusterMetricsReport,
    GetBudgetReportQuery,
    GetClusterMetricsQuery,
)
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.lifecycle import TerminalOutcome
from hexaqueue_core.domain.retry import DeadLetterRecord
from hexaqueue_worker.domain.telemetry import NodeTelemetryPulse

__all__ = [
    "ColumnarAnalyticsAdapter",
]


def _export_dataframe(df: pl.DataFrame, format_name: str) -> bytes:
    """Serialize Polars DataFrame into zero-copy binary or text export payload.

    Args:
        df: Target Polars DataFrame.
        format_name: Target format identifier ('parquet', 'arrow_ipc', 'csv', 'json').

    Returns:
        Binary bytes representing the exported columnar payload.
    """
    buf = io.BytesIO()
    match format_name.lower():
        case "parquet":
            df.write_parquet(buf)
        case "arrow_ipc" | "arrow":
            df.write_ipc(buf)
        case "csv":
            df.write_csv(buf)
        case _:
            buf.write(df.write_json().encode("utf-8"))
    return buf.getvalue()


def _compute_node_percentiles(
    nodes: list[NodeTelemetryPulse],
) -> tuple[float, float, float, float]:
    """Compute CPU percentiles and GPU idle percentage across node telemetry records.

    Args:
        nodes: Registered compute node telemetry pulses.

    Returns:
        Tuple of (p50, p95, p99, gpu_idle_pct).
    """
    if not nodes:
        return 0.0, 0.0, 0.0, 0.0

    rows: list[dict[str, Any]] = []
    for n in nodes:
        total_gpus = len(n.gpu_metrics)
        idle_gpus = sum(
            1 for g in n.gpu_metrics if getattr(g, "utilization_pct", 0.0) == 0.0
        )
        rows.append(
            {
                "cpu": float(n.cpu_utilization_pct),
                "gpu_count": total_gpus,
                "gpu_idle": idle_gpus,
            }
        )

    df_nodes = pl.DataFrame(rows)
    p50 = float(df_nodes.select(pl.col("cpu").quantile(0.50)).item() or 0.0)
    p95 = float(df_nodes.select(pl.col("cpu").quantile(0.95)).item() or 0.0)
    p99 = float(df_nodes.select(pl.col("cpu").quantile(0.99)).item() or 0.0)

    total_gpus_count = int(df_nodes.select(pl.col("gpu_count").sum()).item() or 0)
    total_idle_gpus = int(df_nodes.select(pl.col("gpu_idle").sum()).item() or 0)
    gpu_idle_pct = (
        round((total_idle_gpus / total_gpus_count) * 100.0, 2)
        if total_gpus_count > 0
        else 0.0
    )
    return p50, p95, p99, gpu_idle_pct


def _compute_job_error_classification(
    jobs: list[JobSpec],
) -> tuple[int, dict[str, float]]:
    """Compute error classification distribution across job records.

    Args:
        jobs: Job specifications to evaluate.

    Returns:
        Tuple of (total_jobs_evaluated, error_rate_by_classification).
    """
    if not jobs:
        return 0, {}

    rows = [
        {
            "id": j.id,
            "outcome": j.status.outcome.name if j.status.outcome else "NONE",
            "reason": str(j.status.reason or "UNKNOWN")
            if (
                j.status.outcome == TerminalOutcome.FAILED
                or j.status.reason is not None
            )
            else "NONE",
        }
        for j in jobs
    ]
    df_jobs = pl.DataFrame(rows)
    total_jobs = df_jobs.height

    failed_df = df_jobs.filter(pl.col("outcome") == "FAILED")
    if failed_df.height == 0:
        return total_jobs, {}

    grouped = (
        failed_df.group_by("reason")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
    )
    error_rates: dict[str, float] = {}
    for row in grouped.to_dicts():
        category = str(row["reason"])
        error_rates[category] = round((row["count"] / max(total_jobs, 1)) * 100.0, 2)
    return total_jobs, error_rates


def _compute_dlq_trends(
    dlq_records: list[DeadLetterRecord],
) -> list[dict[str, Any]]:
    """Aggregate DLQ records by failure reason and occurrences.

    Args:
        dlq_records: List of DeadLetterRecord entries.

    Returns:
        List of trend summary dictionaries.
    """
    if not dlq_records:
        return []

    rows = [
        {
            "job_id": d.job_id,
            "failure_reason": d.failure_reason,
            "timestamp": d.timestamp.isoformat(),
        }
        for d in dlq_records
    ]
    df_dlq = pl.DataFrame(rows)
    grouped = (
        df_dlq.group_by("failure_reason")
        .agg(pl.len().alias("occurrences"))
        .sort("occurrences", descending=True)
    )
    return grouped.to_dicts()


class ColumnarAnalyticsAdapter:
    """High-throughput analytical projection adapter powered by Polars and Apache Arrow.

    Notes/Architectural Intent:
        Computes aggregated spend, burn rates, utilization percentiles, and DLQ trends
        directly into columnar Polars DataFrames, returning structured Pydantic models
        or zero-copy binary streaming buffers.
    """

    def __init__(self, engine_or_connection: Any | None = None) -> None:
        """Initialize ColumnarAnalyticsAdapter.

        Args:
            engine_or_connection: Optional database engine or connection.
        """
        self.columnar_adapter = (
            PolarsColumnarAdapter(engine_or_connection=engine_or_connection)
            if engine_or_connection is not None
            else None
        )

    def project_budget_report(
        self,
        query: GetBudgetReportQuery,
        reservations: list[BudgetReservation],
    ) -> BudgetReportResponse | bytes:
        """Project zero-copy budget and spend metrics over rolling time window.

        Args:
            query: Analytical query specification.
            reservations: Budget reservations collection to project.

        Returns:
            BudgetReportResponse for JSON queries or binary bytes for columnar exports.
        """
        if not reservations:
            empty_df = pl.DataFrame(
                schema={
                    "reservation_id": pl.String,
                    "tenant_id": pl.String,
                    "held_credits": pl.Float64,
                    "created_at": pl.Float64,
                }
            )
            if query.format.lower() != "json":
                return _export_dataframe(empty_df, query.format)
            return BudgetReportResponse(
                window_hours=query.window_hours,
                total_spend_credits=0.0,
                burn_rate_credits_per_hour=0.0,
                total_reservations=0,
                by_tenant=[],
            )

        rows = [
            {
                "reservation_id": r.reservation_id,
                "tenant_id": r.tenant_id,
                "held_credits": float(r.held_credits),
                "created_at": r.created_at.timestamp(),
            }
            for r in reservations
        ]
        df = pl.DataFrame(rows)

        if query.tenant_id:
            df = df.filter(pl.col("tenant_id") == query.tenant_id)

        cutoff = (datetime.now(UTC) - timedelta(hours=query.window_hours)).timestamp()
        df = df.filter(pl.col("created_at") >= cutoff)

        if query.format.lower() != "json":
            return _export_dataframe(df, query.format)

        total_spend = (
            float(df.select(pl.col("held_credits").sum()).item() or 0.0)
            if df.height > 0
            else 0.0
        )
        total_count = df.height
        burn_rate = (
            round(total_spend / max(query.window_hours, 1), 4)
            if query.window_hours > 0
            else 0.0
        )

        by_tenant: list[dict[str, Any]] = []
        if df.height > 0:
            grouped = (
                df.group_by("tenant_id")
                .agg(
                    [
                        pl.col("held_credits").sum().alias("total_credits"),
                        pl.len().alias("reservation_count"),
                    ]
                )
                .sort("total_credits", descending=True)
            )
            by_tenant = grouped.to_dicts()

        return BudgetReportResponse(
            window_hours=query.window_hours,
            total_spend_credits=round(total_spend, 4),
            burn_rate_credits_per_hour=burn_rate,
            total_reservations=total_count,
            by_tenant=by_tenant,
        )

    def project_cluster_metrics(
        self,
        query: GetClusterMetricsQuery,
        nodes: list[NodeTelemetryPulse] | None = None,
        jobs: list[JobSpec] | None = None,
        dlq_records: list[DeadLetterRecord] | None = None,
    ) -> ClusterMetricsReport | bytes:
        """Project zero-copy cluster hardware utilization and failure trend metrics.

        Args:
            query: Analytical cluster query specification.
            nodes: Optional registered node telemetry records.
            jobs: Optional evaluated job specifications.
            dlq_records: Optional dead-letter queue records.

        Returns:
            ClusterMetricsReport for JSON queries or binary bytes for columnar exports.
        """
        p50, p95, p99, gpu_idle = _compute_node_percentiles(nodes or [])
        total_jobs, error_rates = _compute_job_error_classification(jobs or [])
        dlq_trends = _compute_dlq_trends(dlq_records or [])

        if query.format.lower() != "json":
            summary_df = pl.DataFrame(
                {
                    "node_utilization_p50": [p50],
                    "node_utilization_p95": [p95],
                    "node_utilization_p99": [p99],
                    "gpu_idle_pct": [gpu_idle],
                    "total_jobs_evaluated": [total_jobs],
                    "window_hours": [query.window_hours],
                }
            )
            return _export_dataframe(summary_df, query.format)

        return ClusterMetricsReport(
            window_hours=query.window_hours,
            node_utilization_p50=p50,
            node_utilization_p95=p95,
            node_utilization_p99=p99,
            gpu_idle_pct=gpu_idle,
            error_rate_by_classification=error_rates,
            dlq_trends=dlq_trends,
            total_jobs_evaluated=total_jobs,
        )
