"""Concrete RBAC policy store adapters (In-Memory, Local SQLite, Oracle ADB).

Notes/Architectural Intent:
    Implements `RbacPolicyPort` across three interchangeable backends:
    1. `OracleAdbRbacPolicyAdapter` for shared HA persistence in Oracle ADB.
    2. `SqliteRbacPolicyAdapter` for local single-node database persistence.
    3. `InMemoryRbacPolicyAdapter` for hermetic testing and ephemeral runs.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hexaqueue_core.utils.imports import require_dependency
from hexaqueue_dashboard.domain.rbac import RbacPrincipal
from hexaqueue_dashboard.ports.rbac import RbacPolicyPort

try:
    import oracledb  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    oracledb = None


class InMemoryRbacPolicyAdapter(RbacPolicyPort):
    """Thread-local in-memory implementation of RbacPolicyPort."""

    def __init__(self, initial: list[RbacPrincipal] | None = None) -> None:
        """Initialize the in-memory store with optional seed principals."""
        self._store: dict[str, RbacPrincipal] = {}
        for item in initial or []:
            self._store[item.principal_id] = item

    def get_principal(self, principal_id: str) -> RbacPrincipal | None:
        """Return principal by ID or None if missing."""
        return self._store.get(principal_id)

    def upsert_principal(self, principal: RbacPrincipal) -> None:
        """Insert or replace a principal record."""
        self._store[principal.principal_id] = principal

    def list_principals(self) -> list[RbacPrincipal]:
        """Return all principals sorted by principal_id."""
        return [self._store[k] for k in sorted(self._store)]

    def delete_principal(self, principal_id: str) -> bool:
        """Remove a principal record if present."""
        return self._store.pop(principal_id, None) is not None


class SqliteRbacPolicyAdapter(RbacPolicyPort):
    """Local SQLite database implementation of RbacPolicyPort."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Initialize local SQLite RBAC store and ensure schema exists.

        Args:
            db_path: Filesystem path to SQLite DB or ':memory:'.
        """
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hxq_rbac_principals (
                principal_id TEXT PRIMARY KEY,
                hashed_secret TEXT NOT NULL,
                roles_json TEXT NOT NULL,
                permissions_json TEXT NOT NULL,
                is_active INTEGER NOT NULL
            )
            """
        )
        self._conn.commit()

    def get_principal(self, principal_id: str) -> RbacPrincipal | None:
        """Fetch an RBAC principal from SQLite."""
        cur = self._conn.execute(
            """
            SELECT principal_id, hashed_secret, roles_json, permissions_json, is_active
            FROM hxq_rbac_principals
            WHERE principal_id = ?
            """,
            (principal_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return RbacPrincipal(
            principal_id=row[0],
            hashed_secret=row[1],
            roles=frozenset(json.loads(row[2])),
            permissions=frozenset(json.loads(row[3])),
            is_active=bool(row[4]),
        )

    def upsert_principal(self, principal: RbacPrincipal) -> None:
        """Insert or update an RBAC principal in SQLite."""
        self._conn.execute(
            """
            INSERT INTO hxq_rbac_principals
                (principal_id, hashed_secret, roles_json, permissions_json, is_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(principal_id) DO UPDATE SET
                hashed_secret = excluded.hashed_secret,
                roles_json = excluded.roles_json,
                permissions_json = excluded.permissions_json,
                is_active = excluded.is_active
            """,
            (
                principal.principal_id,
                principal.hashed_secret,
                json.dumps(sorted(principal.roles)),
                json.dumps(sorted(principal.permissions)),
                1 if principal.is_active else 0,
            ),
        )
        self._conn.commit()

    def list_principals(self) -> list[RbacPrincipal]:
        """List all RBAC principals from SQLite."""
        cur = self._conn.execute(
            """
            SELECT principal_id, hashed_secret, roles_json, permissions_json, is_active
            FROM hxq_rbac_principals
            ORDER BY principal_id ASC
            """
        )
        return [
            RbacPrincipal(
                principal_id=row[0],
                hashed_secret=row[1],
                roles=frozenset(json.loads(row[2])),
                permissions=frozenset(json.loads(row[3])),
                is_active=bool(row[4]),
            )
            for row in cur.fetchall()
        ]

    def delete_principal(self, principal_id: str) -> bool:
        """Delete an RBAC principal from SQLite."""
        cur = self._conn.execute(
            "DELETE FROM hxq_rbac_principals WHERE principal_id = ?",
            (principal_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0


class OracleAdbRbacPolicyAdapter(RbacPolicyPort):
    """Oracle Autonomous Database implementation of RbacPolicyPort."""

    def __init__(
        self,
        *,
        dsn: str | None = None,
        user: str | None = None,
        password: str | None = None,
        wallet_dir: str | None = None,
        connection_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Initialize Oracle ADB RBAC store adapter.

        Args:
            dsn: Oracle ADB TNS alias or EZConnect DSN.
            user: Oracle DB username.
            password: Oracle DB password.
            wallet_dir: Optional Oracle mTLS wallet directory.
            connection_factory: Optional callable returning an open DB-API connection.
        """
        self._dsn = dsn or os.environ.get("HEXAQUEUE_ORACLE_DSN", "")
        self._user = user or os.environ.get("HEXAQUEUE_ORACLE_USER", "ADMIN")
        self._password = password or os.environ.get("HEXAQUEUE_ORACLE_PASSWORD", "")
        self._wallet_dir = wallet_dir or os.environ.get("HEXAQUEUE_ORACLE_WALLET_DIR")
        self._connection_factory = connection_factory
        self._schema_initialized = False

    def _connect(self) -> Any:
        if self._connection_factory is not None:
            return self._connection_factory()
        if oracledb is None:
            require_dependency(
                "oracledb",
                extra="oracle",
                package="hexaqueue-server",
                feature_name="OracleAdbRbacPolicyAdapter",
            )
            raise RuntimeError("oracledb is required for OracleAdbRbacPolicyAdapter")
        kwargs: dict[str, Any] = {
            "user": self._user,
            "password": self._password,
            "dsn": self._dsn,
        }
        if self._wallet_dir:
            kwargs["config_dir"] = self._wallet_dir
            kwargs["wallet_location"] = self._wallet_dir
        return oracledb.connect(**kwargs)

    def _ensure_schema(self, conn: Any) -> None:
        if self._schema_initialized:
            return
        cur = conn.cursor()
        try:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hxq_rbac_principals (
                    principal_id VARCHAR2(128) PRIMARY KEY,
                    hashed_secret VARCHAR2(512) NOT NULL,
                    roles_json CLOB NOT NULL,
                    permissions_json CLOB NOT NULL,
                    is_active NUMBER(1) NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            cur.close()
        self._schema_initialized = True

    def get_principal(self, principal_id: str) -> RbacPrincipal | None:
        """Fetch an RBAC principal from Oracle ADB."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT principal_id, hashed_secret, roles_json, permissions_json, is_active
                    FROM hxq_rbac_principals
                    WHERE principal_id = :1
                    """,
                    (principal_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return RbacPrincipal(
                    principal_id=str(row[0]),
                    hashed_secret=str(row[1]),
                    roles=frozenset(json.loads(str(row[2]))),
                    permissions=frozenset(json.loads(str(row[3]))),
                    is_active=bool(row[4]),
                )
            finally:
                cur.close()
        finally:
            conn.close()

    def upsert_principal(self, principal: RbacPrincipal) -> None:
        """Insert or update an RBAC principal in Oracle ADB."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    MERGE INTO hxq_rbac_principals dst
                    USING (SELECT :1 AS principal_id FROM DUAL) src
                    ON (dst.principal_id = src.principal_id)
                    WHEN MATCHED THEN UPDATE SET
                        hashed_secret = :2,
                        roles_json = :3,
                        permissions_json = :4,
                        is_active = :5
                    WHEN NOT MATCHED THEN INSERT
                        (principal_id, hashed_secret, roles_json, permissions_json, is_active)
                        VALUES (:1, :2, :3, :4, :5)
                    """,
                    (
                        principal.principal_id,
                        principal.hashed_secret,
                        json.dumps(sorted(principal.roles)),
                        json.dumps(sorted(principal.permissions)),
                        1 if principal.is_active else 0,
                    ),
                )
                conn.commit()
            finally:
                cur.close()
        finally:
            conn.close()

    def list_principals(self) -> list[RbacPrincipal]:
        """List all RBAC principals from Oracle ADB."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT principal_id, hashed_secret, roles_json, permissions_json, is_active
                    FROM hxq_rbac_principals
                    ORDER BY principal_id ASC
                    """
                )
                return [
                    RbacPrincipal(
                        principal_id=str(row[0]),
                        hashed_secret=str(row[1]),
                        roles=frozenset(json.loads(str(row[2]))),
                        permissions=frozenset(json.loads(str(row[3]))),
                        is_active=bool(row[4]),
                    )
                    for row in cur.fetchall()
                ]
            finally:
                cur.close()
        finally:
            conn.close()

    def delete_principal(self, principal_id: str) -> bool:
        """Delete an RBAC principal from Oracle ADB."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    "DELETE FROM hxq_rbac_principals WHERE principal_id = :1",
                    (principal_id,),
                )
                deleted = cur.rowcount > 0
                conn.commit()
                return deleted
            finally:
                cur.close()
        finally:
            conn.close()


def create_rbac_policy_store(
    *,
    oracle_dsn: str | None = None,
    sqlite_path: str | Path | None = None,
) -> RbacPolicyPort:
    """Instantiate the configured RbacPolicyPort adapter (Oracle ADB -> SQLite -> Memory).

    Args:
        oracle_dsn: Optional Oracle ADB DSN override.
        sqlite_path: Optional local SQLite DB path override.

    Returns:
        Configured RbacPolicyPort adapter instance.
    """
    effective_dsn = oracle_dsn or os.environ.get("HEXAQUEUE_ORACLE_DSN")
    if effective_dsn:
        return OracleAdbRbacPolicyAdapter(dsn=effective_dsn)
    effective_sqlite = sqlite_path or os.environ.get("HEXAQUEUE_RBAC_DB_PATH")
    if effective_sqlite:
        return SqliteRbacPolicyAdapter(db_path=effective_sqlite)
    return InMemoryRbacPolicyAdapter()


__all__ = [
    "create_rbac_policy_store",
    "InMemoryRbacPolicyAdapter",
    "OracleAdbRbacPolicyAdapter",
    "SqliteRbacPolicyAdapter",
]
