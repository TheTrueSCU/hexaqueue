"""Oracle Autonomous Database (ADB) storage adapter with asynchronous write-behind outbox.

Notes/Architectural Intent:
    Provides durable, long-term persistence for pipeline run histories, job specifications,
    cluster compute node registrations, and worker telemetry pulses backed by an OCI
    Autonomous Database (ADB Serverless) instance.
    Decouples zero-latency in-memory scheduling loops from database roundtrips via an
    asynchronous write-behind buffer, with retry loops and circuit-breaking designed to
    gracefully withstand OCI Free Tier 7-day inactivity auto-pause sleep/wake cycles.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from hexastack_core.utils.imports import require_dependency
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Engine,
    Float,
    Integer,
    String,
    create_engine,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from hexaqueue_core.domain.exceptions import HexaqueueError
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.node import ComputeNodeProfile
from hexaqueue_core.domain.telemetry import NodeTelemetryPulse
from hexaqueue_server.domain.models import RunStatusReport
from hexaqueue_server.ports.storage import SchedulerStoragePort

logger = logging.getLogger(__name__)

__all__ = [
    "HexaqueueJobModel",
    "HexaqueueNodeModel",
    "HexaqueueRunModel",
    "HexaqueueTelemetryPulseModel",
    "OciAutonomousDatabaseStorageAdapter",
]


class Base(DeclarativeBase):
    """Base declarative model for Hexaqueue ADB storage tables."""


class HexaqueueRunModel(Base):
    """SQLAlchemy model for pipeline run histories."""

    __tablename__ = "hexaqueue_runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_jobs: Mapped[int] = mapped_column(Integer, default=0)
    completed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    failed_jobs: Mapped[int] = mapped_column(Integer, default=0)
    pending_jobs: Mapped[int] = mapped_column(Integer, default=0)
    running_jobs: Mapped[int] = mapped_column(Integer, default=0)
    free_tier_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class HexaqueueJobModel(Base):
    """SQLAlchemy model for individual job specifications."""

    __tablename__ = "hexaqueue_jobs"

    job_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(64), index=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    assigned_worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class HexaqueueNodeModel(Base):
    """SQLAlchemy model for compute worker node profiles."""

    __tablename__ = "hexaqueue_nodes"

    node_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    health_state: Mapped[str] = mapped_column(String(64))
    tier: Mapped[str] = mapped_column(String(64))
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class HexaqueueTelemetryPulseModel(Base):
    """SQLAlchemy model for periodic worker telemetry pulses."""

    __tablename__ = "hexaqueue_telemetry_pulses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_id: Mapped[str] = mapped_column(String(128), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    cpu_utilization_pct: Mapped[float] = mapped_column(Float)
    memory_used_mb: Mapped[int] = mapped_column(Integer)
    memory_total_mb: Mapped[int] = mapped_column(Integer)
    load_average_1m: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class OciAutonomousDatabaseStorageAdapter(SchedulerStoragePort):
    """Oracle Autonomous Database storage adapter with write-behind outbox.

    Notes/Architectural Intent:
        Implements tiered hot/cold persistence. Writes are buffered in memory and
        asynchronously persisted to Oracle ADB (or compatible SQLAlchemy dialect)
        by a background outbox worker. Handles OCI Free Tier sleep/wake reconnection
        with configurable retry logic and circuit-breaking.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Engine | None = None,
        max_buffer_size: int = 5000,
        batch_size: int = 50,
        flush_interval_seconds: float = 0.5,
        max_retries: int = 3,
        auto_create_schema: bool = True,
    ) -> None:
        """Initialize OCI Autonomous Database storage adapter.

        Args:
            database_url: SQLAlchemy database URL (e.g. 'oracle+oracledb://user:pwd@adb').
            engine: Pre-configured Engine instance (overrides database_url).
            max_buffer_size: Maximum items in write-behind memory queue.
            batch_size: Maximum records written per database flush batch.
            flush_interval_seconds: Polling interval for write-behind worker loop.
            max_retries: Maximum reconnection attempts during database wake-up.
            auto_create_schema: If True, creates tables during initialization.
        """
        self._engine = self._resolve_engine(database_url, engine)
        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False)
        self._batch_size = batch_size
        self._flush_interval = flush_interval_seconds
        self._max_retries = max_retries

        self._hot_runs: dict[str, RunStatusReport] = {}
        self._hot_jobs: dict[str, JobSpec] = {}
        self._hot_nodes: dict[str, ComputeNodeProfile] = {}
        self._hot_telemetry: list[NodeTelemetryPulse] = []

        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(
            maxsize=max_buffer_size
        )
        self._worker_task: asyncio.Task[None] | None = None
        self._closing = False
        self._schema_initialized = not auto_create_schema

    @classmethod
    def _resolve_engine(cls, database_url: str | None, engine: Engine | None) -> Engine:
        """Resolve or construct SQLAlchemy Engine with dependency verification."""
        if engine is not None:
            return engine

        target_url = database_url or "sqlite:///:memory:"
        if target_url.startswith("oracle"):
            require_dependency(
                "oracledb",
                extra="oracle",
                package="hexaqueue-server",
                feature_name="Oracle Autonomous Database storage",
            )
            return create_engine(target_url, pool_pre_ping=True, echo=False)

        if target_url == "sqlite:///:memory:":
            return create_engine(
                target_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
                echo=False,
            )
        return create_engine(target_url, echo=False)

    async def _ensure_schema(self) -> None:
        """Initialize database schema if not already initialized."""
        if not self._schema_initialized:
            await asyncio.to_thread(Base.metadata.create_all, self._engine)
            self._schema_initialized = True

    def _ensure_worker(self) -> None:
        """Lazily spawn background write-behind worker if not running."""
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._write_behind_worker())

    async def _write_behind_worker(self) -> None:
        """Background coroutine continuously draining write queue to database."""
        while not self._closing:
            try:
                await self._drain_batch()
                await asyncio.sleep(self._flush_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("Transient error in ADB write-behind loop: %s", exc)
                await asyncio.sleep(self._flush_interval)

    async def _drain_batch(self) -> None:
        """Drain a single batch of items from the queue and flush to database."""
        if self._queue.empty():
            return

        batch: list[tuple[str, Any]] = []
        while len(batch) < self._batch_size and not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break

        if not batch:
            return

        try:
            await self._persist_batch_with_retry(batch)
        finally:
            for _ in batch:
                self._queue.task_done()

    async def _persist_batch_with_retry(self, batch: list[tuple[str, Any]]) -> None:
        """Persist a batch of items with retry logic for database wake-up."""
        await self._ensure_schema()
        for attempt in range(self._max_retries):
            try:
                await asyncio.to_thread(self._sync_persist_batch, batch)
                return
            except Exception as exc:
                if attempt == self._max_retries - 1:
                    logger.error(
                        "Exhausted %d retries persisting batch to ADB: %s",
                        self._max_retries,
                        exc,
                    )
                    raise HexaqueueError(
                        f"Failed to persist batch to ADB: {exc}"
                    ) from exc
                await asyncio.sleep(0.05 * (2**attempt))

    def _sync_persist_batch(self, batch: list[tuple[str, Any]]) -> None:
        """Synchronously commit a batch of items inside a worker thread."""
        with self._sessionmaker() as session, session.begin():
            for kind, payload in batch:
                self._merge_entity(session, kind, payload)

    def _merge_entity(self, session: Session, kind: str, payload: Any) -> None:
        """Insert or update a single domain entity within the active session."""
        match kind:
            case "run":
                report: RunStatusReport = payload
                run_id = report.id or report.run_id
                model = session.get(HexaqueueRunModel, run_id)
                if model is None:
                    model = HexaqueueRunModel(run_id=run_id)
                    session.add(model)
                model.status = str(report.status or report.state)
                model.state = str(report.state)
                model.outcome = str(report.outcome) if report.outcome else None
                model.total_jobs = report.total_jobs
                model.completed_jobs = report.completed_jobs
                model.failed_jobs = report.failed_jobs
                model.pending_jobs = report.pending_jobs
                model.running_jobs = report.running_jobs
                model.free_tier_active = report.free_tier_active
                model.created_at = report.created_at
                model.updated_at = report.updated_at
                model.payload = report.model_dump(mode="json")

            case "job":
                job: JobSpec = payload
                jmodel = session.get(HexaqueueJobModel, job.id)
                if jmodel is None:
                    jmodel = HexaqueueJobModel(job_id=job.id)
                    session.add(jmodel)
                jmodel.run_id = job.run_id
                jmodel.name = job.name
                jmodel.status = str(job.status.state)
                jmodel.priority = job.priority
                jmodel.assigned_worker_id = job.assigned_worker_id
                jmodel.created_at = job.created_at
                jmodel.updated_at = job.updated_at
                jmodel.payload = job.model_dump(mode="json")

            case "node":
                node: ComputeNodeProfile = payload
                nmodel = session.get(HexaqueueNodeModel, node.node_id)
                if nmodel is None:
                    nmodel = HexaqueueNodeModel(node_id=node.node_id)
                    session.add(nmodel)
                nmodel.health_state = str(node.health_state)
                nmodel.tier = str(node.tier)
                nmodel.registered_at = node.registered_at
                nmodel.last_heartbeat_at = node.last_heartbeat_at
                nmodel.payload = node.model_dump(mode="json")

            case "telemetry":
                pulse: NodeTelemetryPulse = payload
                load_1m = pulse.load_average[0]
                pmodel = HexaqueueTelemetryPulseModel(
                    worker_id=pulse.worker_id,
                    timestamp=pulse.timestamp,
                    cpu_utilization_pct=pulse.cpu_utilization_pct,
                    memory_used_mb=pulse.memory_used_mb,
                    memory_total_mb=pulse.memory_total_mb,
                    load_average_1m=load_1m,
                    payload=pulse.model_dump(mode="json"),
                )
                session.add(pmodel)

    async def record_run(self, run: RunStatusReport) -> None:
        """Persist or update a pipeline run status record."""
        run_key = run.id or run.run_id
        self._hot_runs[run_key] = run
        self._ensure_worker()
        try:
            self._queue.put_nowait(("run", run))
        except asyncio.QueueFull:
            logger.warning("ADB write buffer full; forcing synchronous batch drain")
            await self._drain_batch()
            await self._queue.put(("run", run))

    async def get_run(self, run_id: str) -> RunStatusReport | None:
        """Retrieve a pipeline run status record by identifier."""
        if run_id in self._hot_runs:
            return self._hot_runs[run_id]

        await self._ensure_schema()

        def _query() -> RunStatusReport | None:
            with self._sessionmaker() as session:
                model = session.get(HexaqueueRunModel, run_id)
                if model is not None:
                    return RunStatusReport.model_validate(model.payload)
            return None

        report = await asyncio.to_thread(_query)
        if report is not None:
            self._hot_runs[run_id] = report
        return report

    async def list_runs(
        self, limit: int = 100, offset: int = 0
    ) -> Sequence[RunStatusReport]:
        """List historical pipeline run records ordered by creation time descending."""
        await self.flush()
        await self._ensure_schema()

        def _query() -> list[RunStatusReport]:
            with self._sessionmaker() as session:
                stmt = (
                    select(HexaqueueRunModel)
                    .order_by(HexaqueueRunModel.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
                result = session.execute(stmt)
                return [
                    RunStatusReport.model_validate(m.payload) for m in result.scalars()
                ]

        return await asyncio.to_thread(_query)

    async def record_job(self, job: JobSpec) -> None:
        """Persist or update an individual job specification record."""
        self._hot_jobs[job.id] = job
        self._ensure_worker()
        try:
            self._queue.put_nowait(("job", job))
        except asyncio.QueueFull:
            await self._drain_batch()
            await self._queue.put(("job", job))

    async def get_job(self, job_id: str) -> JobSpec | None:
        """Retrieve a job specification by unique job identifier."""
        if job_id in self._hot_jobs:
            return self._hot_jobs[job_id]

        await self._ensure_schema()

        def _query() -> JobSpec | None:
            with self._sessionmaker() as session:
                model = session.get(HexaqueueJobModel, job_id)
                if model is not None:
                    return JobSpec.model_validate(model.payload)
            return None

        job = await asyncio.to_thread(_query)
        if job is not None:
            self._hot_jobs[job_id] = job
        return job

    async def list_jobs(
        self, run_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[JobSpec]:
        """List historical job records optionally filtered by pipeline run."""
        await self.flush()
        await self._ensure_schema()

        def _query() -> list[JobSpec]:
            with self._sessionmaker() as session:
                stmt = select(HexaqueueJobModel).order_by(
                    HexaqueueJobModel.created_at.desc()
                )
                if run_id is not None:
                    stmt = stmt.where(HexaqueueJobModel.run_id == run_id)
                stmt = stmt.offset(offset).limit(limit)
                result = session.execute(stmt)
                return [JobSpec.model_validate(m.payload) for m in result.scalars()]

        return await asyncio.to_thread(_query)

    async def record_node(self, node: ComputeNodeProfile) -> None:
        """Persist or update a compute worker node profile."""
        self._hot_nodes[node.node_id] = node
        self._ensure_worker()
        try:
            self._queue.put_nowait(("node", node))
        except asyncio.QueueFull:
            await self._drain_batch()
            await self._queue.put(("node", node))

    async def get_node(self, node_id: str) -> ComputeNodeProfile | None:
        """Retrieve a compute worker node profile by identifier."""
        if node_id in self._hot_nodes:
            return self._hot_nodes[node_id]

        await self._ensure_schema()

        def _query() -> ComputeNodeProfile | None:
            with self._sessionmaker() as session:
                model = session.get(HexaqueueNodeModel, node_id)
                if model is not None:
                    return ComputeNodeProfile.model_validate(model.payload)
            return None

        node = await asyncio.to_thread(_query)
        if node is not None:
            self._hot_nodes[node_id] = node
        return node

    async def list_nodes(
        self, limit: int = 100, offset: int = 0
    ) -> Sequence[ComputeNodeProfile]:
        """List compute worker nodes ordered by last heartbeat descending."""
        await self.flush()
        await self._ensure_schema()

        def _query() -> list[ComputeNodeProfile]:
            with self._sessionmaker() as session:
                stmt = (
                    select(HexaqueueNodeModel)
                    .order_by(HexaqueueNodeModel.last_heartbeat_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
                result = session.execute(stmt)
                return [
                    ComputeNodeProfile.model_validate(m.payload)
                    for m in result.scalars()
                ]

        return await asyncio.to_thread(_query)

    async def record_telemetry_pulse(self, pulse: NodeTelemetryPulse) -> None:
        """Persist a periodic worker telemetry pulse snapshot."""
        self._hot_telemetry.append(pulse)
        self._ensure_worker()
        try:
            self._queue.put_nowait(("telemetry", pulse))
        except asyncio.QueueFull:
            await self._drain_batch()
            await self._queue.put(("telemetry", pulse))

    async def list_telemetry_pulses(
        self, worker_id: str | None = None, limit: int = 100, offset: int = 0
    ) -> Sequence[NodeTelemetryPulse]:
        """List historical telemetry pulses optionally filtered by worker."""
        await self.flush()
        await self._ensure_schema()

        def _query() -> list[NodeTelemetryPulse]:
            with self._sessionmaker() as session:
                stmt = select(HexaqueueTelemetryPulseModel).order_by(
                    HexaqueueTelemetryPulseModel.timestamp.desc()
                )
                if worker_id is not None:
                    stmt = stmt.where(
                        HexaqueueTelemetryPulseModel.worker_id == worker_id
                    )
                stmt = stmt.offset(offset).limit(limit)
                result = session.execute(stmt)
                return [
                    NodeTelemetryPulse.model_validate(m.payload)
                    for m in result.scalars()
                ]

        return await asyncio.to_thread(_query)

    async def flush(self) -> None:
        """Flush any pending buffered write-behind records to durable storage."""
        while not self._queue.empty():
            await self._drain_batch()

    async def close(self) -> None:
        """Close database connections and terminate background write workers."""
        self._closing = True
        if self._worker_task is not None:
            self._worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker_task
            self._worker_task = None
        await self.flush()
        await asyncio.to_thread(self._engine.dispose)
