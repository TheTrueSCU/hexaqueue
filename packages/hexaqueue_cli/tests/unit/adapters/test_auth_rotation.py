"""Unit tests for hexaqueue_cli password rotation adapter (online + offline fallback)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from hexastack_auth.adapters.password import Pbkdf2PasswordHasher
from pydantic import SecretStr

from hexaqueue_cli.adapters.auth_rotation import (
    rotate_dashboard_password,
    rotate_password_offline,
    rotate_password_online,
)


def _init_sqlite_rbac(db_path: Path, username: str, password: str) -> None:
    hasher = Pbkdf2PasswordHasher()
    hashed = hasher.hash_password(password)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS hxq_rbac_principals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                principal_id TEXT UNIQUE NOT NULL,
                hashed_secret TEXT NOT NULL,
                permissions_json TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        conn.execute(
            """
            INSERT INTO hxq_rbac_principals (principal_id, hashed_secret, permissions_json, is_active)
            VALUES (?, ?, '[]', 1)
            """,
            (username, hashed),
        )
        conn.commit()


def test_rotate_password_online_success_and_error() -> None:
    """Verify online rotation posts SecretStr payload and surfaces HTTP errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        if body["current_secret"] == "wrong":
            return httpx.Response(
                401, json={"detail": "Invalid username or credential."}
            )
        return httpx.Response(
            200,
            json={"status": "rotated", "principal_id": body["username"]},
        )

    transport = httpx.MockTransport(handler)
    msg = rotate_password_online(
        "http://127.0.0.1:8080",
        "rjdw",
        SecretStr("old-secret"),
        SecretStr("new-secret"),
        transport=transport,
    )
    assert "rjdw" in msg

    with pytest.raises(ValueError, match="HTTP 401"):
        rotate_password_online(
            "http://127.0.0.1:8080",
            "rjdw",
            SecretStr("wrong"),
            SecretStr("new-secret"),
            transport=transport,
        )


def test_rotate_password_offline_sqlite_and_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify offline SQLite rotation and automatic fallback when dashboard is unreachable."""
    monkeypatch.delenv("HEXAQUEUE_ORACLE_ADB_DSN", raising=False)
    db_path = tmp_path / "rbac.db"
    _init_sqlite_rbac(db_path, "rjdw", "initial-pw")
    monkeypatch.setenv("HEXAQUEUE_RBAC_DB_PATH", str(db_path))

    def unreachable_handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    msg = rotate_dashboard_password(
        "rjdw",
        SecretStr("initial-pw"),
        SecretStr("rotated-pw"),
        dashboard_url="http://127.0.0.1:8080",
        transport=httpx.MockTransport(unreachable_handler),
    )
    assert "offline in SQLite" in msg

    hasher = Pbkdf2PasswordHasher()
    with sqlite3.connect(str(db_path)) as conn:
        row = conn.execute(
            "SELECT hashed_secret FROM hxq_rbac_principals WHERE principal_id = 'rjdw'"
        ).fetchone()
    assert row is not None
    verified_new = hasher.verify_password("rotated-pw", str(row[0]))
    assert verified_new is True

    with pytest.raises(ValueError, match="Current password verification failed"):
        rotate_password_offline(
            "rjdw",
            SecretStr("wrong-pw"),
            SecretStr("another-pw"),
        )


def test_rotate_password_offline_requires_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify missing ADB/SQLite configuration raises RuntimeError."""
    monkeypatch.delenv("HEXAQUEUE_ORACLE_ADB_DSN", raising=False)
    monkeypatch.delenv("HEXAQUEUE_RBAC_DB_PATH", raising=False)
    with pytest.raises(RuntimeError, match="No offline RBAC store configured"):
        rotate_password_offline(
            "rjdw",
            SecretStr("old"),
            SecretStr("new"),
        )
