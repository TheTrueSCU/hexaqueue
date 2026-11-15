"""Unit tests for InMemory, SQLite, and Oracle ADB RBAC policy store adapters."""

from __future__ import annotations

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
        roles=frozenset({"admin", "ci"}),
    )
    p_guest = RbacPrincipal(
        principal_id="guest-1",
        hashed_secret="pbkdf2$hash-guest",
    )
    store.upsert_principal(p_admin)
    store.upsert_principal(p_guest)

    fetched = store.get_principal("rjdw")
    assert fetched is not None
    assert fetched.roles == frozenset({"admin", "ci"})

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
    """Verify InMemoryRbacPolicyAdapter and normalized SqliteRbacPolicyAdapter."""
    _exercise_store(InMemoryRbacPolicyAdapter())
    db_file = tmp_path / "rbac.db"
    sqlite_store = SqliteRbacPolicyAdapter(db_path=db_file)
    _exercise_store(sqlite_store)
    assert db_file.exists() is True

    # Verify normalized 3-table schema, autoincrement PKs, and UNIQUE(principal_pk, role_pk)
    with sqlite3.connect(db_file) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "hxq_rbac_principals" in tables
        assert "hxq_rbac_roles" in tables
        assert "hxq_rbac_principal_roles" in tables

        # Cascade delete removed guest-1 links; only rjdw links remain
        links = conn.execute(
            "SELECT principal_pk, role_pk FROM hxq_rbac_principal_roles"
        ).fetchall()
        assert len(links) == 2

        # Duplicate (principal_pk, role_pk) tuple must raise IntegrityError
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO hxq_rbac_principal_roles (principal_pk, role_pk) VALUES (?, ?)",
                links[0],
            )


def test_oracle_adb_rbac_store_with_hermetic_connection() -> None:
    """Verify OracleAdbRbacPolicyAdapter normalized 3-table queries via fake DB-API."""
    principals: dict[str, tuple[int, str, str, str, int]] = {}
    roles: dict[str, tuple[int, str]] = {}
    links: set[tuple[int, int]] = set()
    seq = {"p": 0, "r": 0}

    class _FakeCursor:
        def __init__(self) -> None:
            self._results: list[Any] = []
            self.rowcount = 0

        def execute(
            self,
            sql: str,
            params: tuple[Any, ...] | dict[str, Any] = (),
        ) -> None:
            norm = " ".join(sql.split()).upper()
            if norm.startswith("CREATE TABLE"):
                return
            if norm.startswith("MERGE INTO HXQ_RBAC_PRINCIPALS"):
                assert isinstance(params, dict)
                pid = params["principal_id"]
                secret = params["hashed_secret"]
                p_json = params["permissions_json"]
                active = params["is_active"]
                if pid in principals:
                    pk = principals[pid][0]
                else:
                    seq["p"] += 1
                    pk = seq["p"]
                principals[pid] = (pk, pid, secret, p_json, active)
                self.rowcount = 1
            elif norm.startswith("MERGE INTO HXQ_RBAC_ROLES"):
                assert isinstance(params, dict)
                rname = params["role_name"]
                if rname not in roles:
                    seq["r"] += 1
                    roles[rname] = (seq["r"], rname)
                self.rowcount = 1
            elif norm.startswith("MERGE INTO HXQ_RBAC_PRINCIPAL_ROLES"):
                assert isinstance(params, dict)
                links.add((int(params["principal_pk"]), int(params["role_pk"])))
                self.rowcount = 1
            elif norm.startswith("SELECT ID FROM HXQ_RBAC_PRINCIPALS"):
                assert isinstance(params, tuple)
                row = principals.get(params[0])
                self._results = [(row[0],)] if row else []
            elif norm.startswith("SELECT ID FROM HXQ_RBAC_ROLES"):
                assert isinstance(params, tuple)
                row = roles.get(params[0])
                self._results = [(row[0],)] if row else []
            elif norm.startswith("SELECT R.ROLE_NAME"):
                assert isinstance(params, tuple)
                pk = int(params[0])
                id_to_name = {v[0]: v[1] for v in roles.values()}
                self._results = [
                    (id_to_name[r_pk],) for p_pk, r_pk in links if p_pk == pk
                ]
            elif "WHERE PRINCIPAL_ID = :1" in norm and norm.startswith("SELECT"):
                assert isinstance(params, tuple)
                row = principals.get(params[0])
                self._results = [row] if row else []
            elif norm.startswith("SELECT ID, PRINCIPAL_ID"):
                self._results = [principals[k] for k in sorted(principals)]
            elif norm.startswith("DELETE FROM HXQ_RBAC_PRINCIPAL_ROLES"):
                assert isinstance(params, tuple)
                pk = int(params[0])
                to_drop = {pair for pair in links if pair[0] == pk}
                links.difference_update(to_drop)
                self.rowcount = len(to_drop)
            elif norm.startswith("DELETE FROM HXQ_RBAC_PRINCIPALS"):
                assert isinstance(params, tuple)
                removed = principals.pop(params[0], None)
                if removed is not None:
                    to_drop = {pair for pair in links if pair[0] == removed[0]}
                    links.difference_update(to_drop)
                    self.rowcount = 1
                else:
                    self.rowcount = 0

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
    assert "rjdw" in principals
    assert "admin" in roles
    assert "ci" in roles
    assert len(links) == 2


def test_create_rbac_policy_store_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify store factory selects Oracle ADB -> SQLite -> InMemory."""
    monkeypatch.delenv("HEXAQUEUE_ORACLE_ADB_DSN", raising=False)
    monkeypatch.delenv("HEXAQUEUE_RBAC_DB_PATH", raising=False)

    mem_store = create_rbac_policy_store()
    assert isinstance(mem_store, InMemoryRbacPolicyAdapter)

    sqlite_store = create_rbac_policy_store(sqlite_path=tmp_path / "local.db")
    assert isinstance(sqlite_store, SqliteRbacPolicyAdapter)

    oracle_store = create_rbac_policy_store(oracle_dsn="hexaqueue_adb_high")
    assert isinstance(oracle_store, OracleAdbRbacPolicyAdapter)
