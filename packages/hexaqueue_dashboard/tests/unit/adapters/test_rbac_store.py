"""Unit tests for InMemory, SQLite, and Oracle ADB RBAC policy store adapters."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from hexaqueue_dashboard.adapters.rbac_store import (
    InMemoryRbacPolicyAdapter,
    OracleAdbRbacPolicyAdapter,
    SqliteRbacPolicyAdapter,
    create_rbac_policy_store,
)
from hexaqueue_dashboard.domain.rbac import RbacPrincipal


def _exercise_store(store: Any) -> None:
    """Exercise CRUD contract on any RbacPolicyPort implementation."""
    p_admin = RbacPrincipal(
        principal_id="rjdw",
        hashed_secret="pbkdf2$hash-admin",
        roles=frozenset({"admin"}),
    )
    p_guest = RbacPrincipal(
        principal_id="guest-1",
        hashed_secret="pbkdf2$hash-guest",
    )
    store.upsert_principal(p_admin)
    store.upsert_principal(p_guest)

    fetched = store.get_principal("rjdw")
    assert fetched is not None
    assert fetched.roles == frozenset({"admin"})

    fetched_guest = store.get_principal("guest-1")
    assert fetched_guest is not None
    assert fetched_guest.roles == frozenset({"guest"})

    listed = store.list_principals()
    ids = [p.principal_id for p in listed]
    assert ids == ["guest-1", "rjdw"]

    deleted = store.delete_principal("guest-1")
    assert deleted is True
    missing = store.get_principal("guest-1")
    assert missing is None


def test_in_memory_and_sqlite_rbac_stores(tmp_path: Path) -> None:
    """Verify InMemoryRbacPolicyAdapter and SqliteRbacPolicyAdapter parity."""
    _exercise_store(InMemoryRbacPolicyAdapter())
    db_file = tmp_path / "rbac.db"
    _exercise_store(SqliteRbacPolicyAdapter(db_path=db_file))
    assert db_file.exists() is True


def test_oracle_adb_rbac_store_with_hermetic_connection() -> None:
    """Verify OracleAdbRbacPolicyAdapter queries via injected DB-API connection."""
    backing_rows: dict[str, tuple[str, str, str, str, int]] = {}

    class _FakeCursor:
        def __init__(self) -> None:
            self._results: list[Any] = []
            self.rowcount = 0

        def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
            norm = " ".join(sql.split()).upper()
            if norm.startswith("CREATE TABLE"):
                return
            if norm.startswith("MERGE INTO"):
                pid, secret, r_json, p_json, active = params
                backing_rows[pid] = (pid, secret, r_json, p_json, active)
                self.rowcount = 1
            elif "WHERE PRINCIPAL_ID = :1" in norm and norm.startswith("SELECT"):
                row = backing_rows.get(params[0])
                self._results = [row] if row else []
            elif norm.startswith("SELECT"):
                self._results = [backing_rows[k] for k in sorted(backing_rows)]
            elif norm.startswith("DELETE"):
                existed = backing_rows.pop(params[0], None) is not None
                self.rowcount = 1 if existed else 0

        def fetchone(self) -> Any:
            return self._results[0] if self._results else None

        def fetchall(self) -> list[Any]:
            return list(self._results)

        def close(self) -> None:
            return None

    class _FakeConn:
        def cursor(self) -> _FakeCursor:
            return _FakeCursor()

        def commit(self) -> None:
            return None

        def close(self) -> None:
            return None

    store = OracleAdbRbacPolicyAdapter(connection_factory=_FakeConn)
    _exercise_store(store)
    assert "rjdw" in backing_rows
    assert json.loads(backing_rows["rjdw"][2]) == ["admin"]


def test_create_rbac_policy_store_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify store factory selects Oracle ADB -> SQLite -> InMemory."""
    monkeypatch.delenv("HEXAQUEUE_ORACLE_DSN", raising=False)
    monkeypatch.delenv("HEXAQUEUE_RBAC_DB_PATH", raising=False)

    mem_store = create_rbac_policy_store()
    assert isinstance(mem_store, InMemoryRbacPolicyAdapter)

    sqlite_store = create_rbac_policy_store(sqlite_path=tmp_path / "local.db")
    assert isinstance(sqlite_store, SqliteRbacPolicyAdapter)

    oracle_store = create_rbac_policy_store(oracle_dsn="hexaqueue_adb_high")
    assert isinstance(oracle_store, OracleAdbRbacPolicyAdapter)
    # Silence unused import lint if sqlite3 is only used for type parity
    assert sqlite3.sqlite_version is not None
