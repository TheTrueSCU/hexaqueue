"""Concrete RBAC policy store adapters (In-Memory, Local SQLite, Oracle ADB).

Notes/Architectural Intent:
    Implements `RbacPolicyPort` across three interchangeable backends:
    1. `OracleAdbRbacPolicyAdapter` for shared HA persistence in Oracle ADB.
    2. `SqliteRbacPolicyAdapter` for local single-node database persistence.
    3. `InMemoryRbacPolicyAdapter` for hermetic testing and ephemeral runs.
    Relational backends normalize principals (`hxq_rbac_principals`), roles
    (`hxq_rbac_roles`), and their many-to-many link (`hxq_rbac_principal_roles`)
    with autoincrementing integer primary keys and unique `(principal_pk, role_pk)`
    constraints.
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
    """Normalized local SQLite database implementation of RbacPolicyPort."""

    def __init__(self, db_path: str | Path = ":memory:") -> None:
        """Initialize local SQLite RBAC tables and foreign-key constraints.

        Args:
            db_path: Filesystem path to SQLite DB or ':memory:'.
        """
        self._db_path = str(db_path)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS hxq_rbac_principals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                principal_id TEXT NOT NULL UNIQUE,
                hashed_secret TEXT NOT NULL,
                permissions_json TEXT NOT NULL,
                is_active INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS hxq_rbac_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role_name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS hxq_rbac_principal_roles (
                principal_pk INTEGER NOT NULL REFERENCES hxq_rbac_principals(id) ON DELETE CASCADE,
                role_pk INTEGER NOT NULL REFERENCES hxq_rbac_roles(id) ON DELETE CASCADE,
                UNIQUE (principal_pk, role_pk)
            );
            """
        )
        self._conn.commit()

    def _fetch_roles_for_pk(self, principal_pk: int) -> frozenset[str]:
        cur = self._conn.execute(
            """
            SELECT r.role_name
            FROM hxq_rbac_roles r
            JOIN hxq_rbac_principal_roles pr ON pr.role_pk = r.id
            WHERE pr.principal_pk = ?
            """,
            (principal_pk,),
        )
        roles = {row[0] for row in cur.fetchall()}
        return frozenset(roles) if roles else frozenset({"guest"})

    def get_principal(self, principal_id: str) -> RbacPrincipal | None:
        """Fetch an RBAC principal and its linked roles from SQLite."""
        cur = self._conn.execute(
            """
            SELECT id, principal_id, hashed_secret, permissions_json, is_active
            FROM hxq_rbac_principals
            WHERE principal_id = ?
            """,
            (principal_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return RbacPrincipal(
            principal_id=row[1],
            hashed_secret=row[2],
            roles=self._fetch_roles_for_pk(int(row[0])),
            permissions=frozenset(json.loads(row[3])),
            is_active=bool(row[4]),
        )

    def upsert_principal(self, principal: RbacPrincipal) -> None:
        """Insert or update an RBAC principal and its normalized role links."""
        self._conn.execute(
            """
            INSERT INTO hxq_rbac_principals
                (principal_id, hashed_secret, permissions_json, is_active)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(principal_id) DO UPDATE SET
                hashed_secret = excluded.hashed_secret,
                permissions_json = excluded.permissions_json,
                is_active = excluded.is_active
            """,
            (
                principal.principal_id,
                principal.hashed_secret,
                json.dumps(sorted(principal.permissions)),
                1 if principal.is_active else 0,
            ),
        )
        row = self._conn.execute(
            "SELECT id FROM hxq_rbac_principals WHERE principal_id = ?",
            (principal.principal_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(
                f"Failed to resolve principal PK for '{principal.principal_id}'"
            )
        principal_pk = int(row[0])

        self._conn.execute(
            "DELETE FROM hxq_rbac_principal_roles WHERE principal_pk = ?",
            (principal_pk,),
        )
        effective_roles = principal.roles or frozenset({"guest"})
        for role_name in sorted(effective_roles):
            self._conn.execute(
                "INSERT OR IGNORE INTO hxq_rbac_roles (role_name) VALUES (?)",
                (role_name,),
            )
            role_row = self._conn.execute(
                "SELECT id FROM hxq_rbac_roles WHERE role_name = ?",
                (role_name,),
            ).fetchone()
            if role_row is None:
                raise RuntimeError(f"Failed to resolve role PK for '{role_name}'")
            self._conn.execute(
                """
                INSERT OR IGNORE INTO hxq_rbac_principal_roles (principal_pk, role_pk)
                VALUES (?, ?)
                """,
                (principal_pk, int(role_row[0])),
            )
        self._conn.commit()

    def list_principals(self) -> list[RbacPrincipal]:
        """List all RBAC principals and their linked roles from SQLite."""
        cur = self._conn.execute(
            """
            SELECT id, principal_id, hashed_secret, permissions_json, is_active
            FROM hxq_rbac_principals
            ORDER BY principal_id ASC
            """
        )
        return [
            RbacPrincipal(
                principal_id=row[1],
                hashed_secret=row[2],
                roles=self._fetch_roles_for_pk(int(row[0])),
                permissions=frozenset(json.loads(row[3])),
                is_active=bool(row[4]),
            )
            for row in cur.fetchall()
        ]

    def delete_principal(self, principal_id: str) -> bool:
        """Delete an RBAC principal (cascading link rows) from SQLite."""
        cur = self._conn.execute(
            "DELETE FROM hxq_rbac_principals WHERE principal_id = ?",
            (principal_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0


class OracleAdbRbacPolicyAdapter(RbacPolicyPort):
    """Normalized Oracle Autonomous Database implementation of RbacPolicyPort."""

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
        self._dsn = dsn or os.environ.get("HEXAQUEUE_ORACLE_ADB_DSN", "")
        self._user = user or os.environ.get("HEXAQUEUE_ORACLE_ADB_USER", "ADMIN")
        self._password = password or os.environ.get("HEXAQUEUE_ORACLE_ADB_PASSWORD", "")
        self._wallet_dir = wallet_dir or os.environ.get(
            "HEXAQUEUE_ORACLE_ADB_WALLET_DIR"
        )
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
                    id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    principal_id VARCHAR2(128) NOT NULL UNIQUE,
                    hashed_secret VARCHAR2(512) NOT NULL,
                    permissions_json CLOB NOT NULL,
                    is_active NUMBER(1) NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hxq_rbac_roles (
                    id NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    role_name VARCHAR2(64) NOT NULL UNIQUE
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hxq_rbac_principal_roles (
                    principal_pk NUMBER NOT NULL
                        REFERENCES hxq_rbac_principals(id) ON DELETE CASCADE,
                    role_pk NUMBER NOT NULL
                        REFERENCES hxq_rbac_roles(id) ON DELETE CASCADE,
                    CONSTRAINT uq_hxq_principal_role UNIQUE (principal_pk, role_pk)
                )
                """
            )
            conn.commit()
        finally:
            cur.close()
        self._schema_initialized = True

    def _fetch_roles_for_pk(self, cur: Any, principal_pk: int) -> frozenset[str]:
        cur.execute(
            """
            SELECT r.role_name
            FROM hxq_rbac_roles r
            JOIN hxq_rbac_principal_roles pr ON pr.role_pk = r.id
            WHERE pr.principal_pk = :1
            """,
            (principal_pk,),
        )
        roles = {str(r[0]) for r in cur.fetchall()}
        return frozenset(roles) if roles else frozenset({"guest"})

    def get_principal(self, principal_id: str) -> RbacPrincipal | None:
        """Fetch an RBAC principal and its linked roles from Oracle ADB."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT id, principal_id, hashed_secret, permissions_json, is_active
                    FROM hxq_rbac_principals
                    WHERE principal_id = :1
                    """,
                    (principal_id,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return RbacPrincipal(
                    principal_id=str(row[1]),
                    hashed_secret=str(row[2]),
                    roles=self._fetch_roles_for_pk(cur, int(row[0])),
                    permissions=frozenset(json.loads(str(row[3]))),
                    is_active=bool(row[4]),
                )
            finally:
                cur.close()
        finally:
            conn.close()

    def upsert_principal(self, principal: RbacPrincipal) -> None:
        """Insert or update an RBAC principal and its normalized role links in Oracle ADB."""
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
                        permissions_json = :3,
                        is_active = :4
                    WHEN NOT MATCHED THEN INSERT
                        (principal_id, hashed_secret, permissions_json, is_active)
                        VALUES (:1, :2, :3, :4)
                    """,
                    (
                        principal.principal_id,
                        principal.hashed_secret,
                        json.dumps(sorted(principal.permissions)),
                        1 if principal.is_active else 0,
                    ),
                )
                cur.execute(
                    "SELECT id FROM hxq_rbac_principals WHERE principal_id = :1",
                    (principal.principal_id,),
                )
                pk_row = cur.fetchone()
                if pk_row is None:
                    raise RuntimeError(
                        f"Failed to resolve principal PK for '{principal.principal_id}'"
                    )
                principal_pk = int(pk_row[0])

                cur.execute(
                    "DELETE FROM hxq_rbac_principal_roles WHERE principal_pk = :1",
                    (principal_pk,),
                )
                for role_name in sorted(principal.roles or frozenset({"guest"})):
                    cur.execute(
                        """
                        MERGE INTO hxq_rbac_roles dst
                        USING (SELECT :1 AS role_name FROM DUAL) src
                        ON (dst.role_name = src.role_name)
                        WHEN NOT MATCHED THEN INSERT (role_name) VALUES (:1)
                        """,
                        (role_name,),
                    )
                    cur.execute(
                        "SELECT id FROM hxq_rbac_roles WHERE role_name = :1",
                        (role_name,),
                    )
                    role_row = cur.fetchone()
                    if role_row is None:
                        raise RuntimeError(
                            f"Failed to resolve role PK for '{role_name}'"
                        )
                    cur.execute(
                        """
                        MERGE INTO hxq_rbac_principal_roles dst
                        USING (SELECT :1 AS principal_pk, :2 AS role_pk FROM DUAL) src
                        ON (dst.principal_pk = src.principal_pk AND dst.role_pk = src.role_pk)
                        WHEN NOT MATCHED THEN INSERT (principal_pk, role_pk) VALUES (:1, :2)
                        """,
                        (principal_pk, int(role_row[0])),
                    )
                conn.commit()
            finally:
                cur.close()
        finally:
            conn.close()

    def list_principals(self) -> list[RbacPrincipal]:
        """List all RBAC principals and their linked roles from Oracle ADB."""
        conn = self._connect()
        try:
            self._ensure_schema(conn)
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT id, principal_id, hashed_secret, permissions_json, is_active
                    FROM hxq_rbac_principals
                    ORDER BY principal_id ASC
                    """
                )
                rows = cur.fetchall()
                return [
                    RbacPrincipal(
                        principal_id=str(row[1]),
                        hashed_secret=str(row[2]),
                        roles=self._fetch_roles_for_pk(cur, int(row[0])),
                        permissions=frozenset(json.loads(str(row[3]))),
                        is_active=bool(row[4]),
                    )
                    for row in rows
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
    effective_dsn = oracle_dsn or os.environ.get("HEXAQUEUE_ORACLE_ADB_DSN")
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
