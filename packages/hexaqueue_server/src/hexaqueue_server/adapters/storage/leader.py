"""SQL database leader election adapter with TTL lease fencing.

Notes/Architectural Intent:
    Implements LeaderElectionPort backed by a relational database (PostgreSQL,
    Oracle Autonomous Database, or SQLite) using a dedicated `hexaqueue_leader_leases`
    row with atomic transaction isolation and UTC TTL expiration fencing to prevent
    split-brain scheduling across active/standby controller instances.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Engine, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from hexaqueue_core.domain.coordination import CrossLoopAsyncLock, LeaderLease
from hexaqueue_core.ports.coordination import LeaderElectionPort


class _LeaderBase(DeclarativeBase):
    """Base declarative class for leader election persistence."""


class HexaqueueLeaderLeaseModel(_LeaderBase):
    """SQLAlchemy model representing a distributed leader election lease row."""

    __tablename__ = "hexaqueue_leader_leases"

    lease_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    leader_id: Mapped[str] = mapped_column(String(128), index=True)
    lease_duration_seconds: Mapped[float] = mapped_column(Float)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    renewal_count: Mapped[int] = mapped_column(Integer, default=0)


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize naive SQLite timestamps to UTC-aware datetimes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class DatabaseLeaderElectionAdapter(LeaderElectionPort):
    """Database-backed leader election adapter using TTL row fencing.

    Args:
        database_url: Optional SQLAlchemy connection string (defaults to in-memory SQLite).
        engine: Optional pre-configured SQLAlchemy Engine.
        lease_key: Logical cluster lease key name.

    Notes/Architectural Intent:
        Uses transactional row locking and UTC expiration checks to coordinate
        active/standby failover across PostgreSQL, Oracle ADB, or SQLite.
    """

    def __init__(
        self,
        database_url: str | None = None,
        *,
        engine: Engine | None = None,
        lease_key: str = "hexaqueue-primary-controller",
    ) -> None:
        """Initialize database leader election adapter."""
        if engine is not None:
            self._engine = engine
        else:
            url = database_url or "sqlite:///:memory:"
            if url == "sqlite:///:memory:":
                self._engine = create_engine(
                    url,
                    connect_args={"check_same_thread": False},
                    poolclass=StaticPool,
                    echo=False,
                )
            else:
                self._engine = create_engine(url, pool_pre_ping=True, echo=False)

        self._sessionmaker = sessionmaker(self._engine, expire_on_commit=False)
        self._lease_key = lease_key
        self._schema_initialized = False
        self._lock = CrossLoopAsyncLock()

    async def _ensure_schema(self) -> None:
        """Create leader lease table if not already initialized."""
        if not self._schema_initialized:
            await asyncio.to_thread(_LeaderBase.metadata.create_all, self._engine)
            self._schema_initialized = True

    @staticmethod
    def _to_domain(row: HexaqueueLeaderLeaseModel) -> LeaderLease:
        """Convert ORM row to domain LeaderLease."""
        return LeaderLease(
            acquired_at=_ensure_utc(row.acquired_at),
            expires_at=_ensure_utc(row.expires_at),
            leader_id=row.leader_id,
            lease_duration_seconds=row.lease_duration_seconds,
            renewal_count=row.renewal_count,
        )

    async def acquire_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Attempt to acquire or renew leadership in the database."""
        await self._ensure_schema()

        def _sync_acquire() -> tuple[bool, bool, str | None]:
            now = datetime.now(UTC)
            expires = now + timedelta(seconds=lease_duration_seconds)
            with self._sessionmaker() as session, session.begin():
                row = session.get(HexaqueueLeaderLeaseModel, self._lease_key)
                if row is not None:
                    row_expires = _ensure_utc(row.expires_at)
                    if now < row_expires:
                        if row.leader_id == candidate_id:
                            row.expires_at = expires
                            row.lease_duration_seconds = lease_duration_seconds
                            row.renewal_count += 1
                            return True, False, None
                        return False, False, None

                    prev_leader = (
                        row.leader_id if row.leader_id != candidate_id else None
                    )
                    row.leader_id = candidate_id
                    row.acquired_at = now
                    row.expires_at = expires
                    row.lease_duration_seconds = lease_duration_seconds
                    row.renewal_count = 0
                    return True, True, prev_leader

                new_row = HexaqueueLeaderLeaseModel(
                    lease_key=self._lease_key,
                    leader_id=candidate_id,
                    lease_duration_seconds=lease_duration_seconds,
                    acquired_at=now,
                    expires_at=expires,
                    renewal_count=0,
                )
                session.add(new_row)
                return True, True, None

        async with self._lock:
            acquired, newly_elected, deposed = await asyncio.to_thread(_sync_acquire)

        if deposed is not None:
            await self._notify_deposed(deposed)
        if newly_elected:
            await self._notify_elected(candidate_id)
        return acquired

    async def renew_leadership(
        self,
        candidate_id: str,
        lease_duration_seconds: float = 15.0,
    ) -> bool:
        """Renew active leadership lease in the database."""
        await self._ensure_schema()

        def _sync_renew() -> tuple[bool, str | None]:
            now = datetime.now(UTC)
            with self._sessionmaker() as session, session.begin():
                row = session.get(HexaqueueLeaderLeaseModel, self._lease_key)
                if row is None:
                    return False, None
                row_expires = _ensure_utc(row.expires_at)
                if now >= row_expires:
                    deposed = candidate_id if row.leader_id == candidate_id else None
                    session.delete(row)
                    return False, deposed
                if row.leader_id != candidate_id:
                    return False, None

                row.expires_at = now + timedelta(seconds=lease_duration_seconds)
                row.lease_duration_seconds = lease_duration_seconds
                row.renewal_count += 1
                return True, None

        async with self._lock:
            renewed, deposed = await asyncio.to_thread(_sync_renew)

        if deposed is not None:
            await self._notify_deposed(deposed)
        return renewed

    async def release_leadership(self, candidate_id: str) -> None:
        """Voluntarily release active leadership row if held by candidate."""
        await self._ensure_schema()

        def _sync_release() -> bool:
            with self._sessionmaker() as session, session.begin():
                row = session.get(HexaqueueLeaderLeaseModel, self._lease_key)
                if row is not None and row.leader_id == candidate_id:
                    session.delete(row)
                    return True
                return False

        async with self._lock:
            released = await asyncio.to_thread(_sync_release)

        if released:
            await self._notify_deposed(candidate_id)

    async def get_current_leader(self) -> LeaderLease | None:
        """Retrieve currently active database leadership lease if unexpired."""
        await self._ensure_schema()

        def _sync_get() -> tuple[LeaderLease | None, str | None]:
            now = datetime.now(UTC)
            with self._sessionmaker() as session, session.begin():
                row = session.get(HexaqueueLeaderLeaseModel, self._lease_key)
                if row is None:
                    return None, None
                if now >= _ensure_utc(row.expires_at):
                    expired_leader = row.leader_id
                    session.delete(row)
                    return None, expired_leader
                return self._to_domain(row), None

        async with self._lock:
            lease, expired_leader = await asyncio.to_thread(_sync_get)

        if expired_leader is not None:
            await self._notify_deposed(expired_leader)
        return lease

    async def is_leader(self, candidate_id: str) -> bool:
        """Check whether candidate currently holds active database leadership."""
        lease = await self.get_current_leader()
        return lease is not None and lease.leader_id == candidate_id

    def close(self) -> None:
        """Dispose underlying SQLAlchemy engine connection pool."""
        self._engine.dispose()


__all__ = [
    "DatabaseLeaderElectionAdapter",
    "HexaqueueLeaderLeaseModel",
]
