"""Password rotation adapter for Hexaqueue CLI (HTTP with offline ADB/SQLite fallback).

Notes/Architectural Intent:
    Keeps hexaqueue-cli decoupled from hexaqueue-dashboard (sibling layer in
    .importlinter) by calling POST /dashboard/auth/rotate-password over HTTP
    and falling back to direct Oracle ADB or SQLite updates when offline.
"""

from __future__ import annotations

import os
import sqlite3
from typing import Any

import httpx
from hexastack_auth.adapters.password import Pbkdf2PasswordHasher
from pydantic import SecretStr

try:
    import oracledb
except ImportError:
    oracledb = None  # type: ignore[assignment]


def _extract_error_detail(response: httpx.Response) -> str:
    """Extract an error message from a failed HTTP response without raising."""
    try:
        payload = response.json()
        if isinstance(payload, dict) and "detail" in payload:
            return str(payload["detail"])
    except ValueError:
        # Non-JSON error bodies fall back to response.text below.
        return response.text
    return response.text


def rotate_password_online(
    dashboard_url: str,
    username: str,
    current_secret: SecretStr,
    new_secret: SecretStr,
    *,
    timeout: float = 10.0,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Rotate a dashboard principal password via the running dashboard HTTP API.

    Args:
        dashboard_url: Base URL of the Hexaqueue dashboard.
        username: Principal username to update.
        current_secret: Existing credential wrapped in SecretStr.
        new_secret: Replacement credential wrapped in SecretStr.
        timeout: HTTP timeout in seconds.
        transport: Optional custom httpx transport for hermetic testing.

    Returns:
        Confirmation message describing the online rotation target.

    Raises:
        ConnectionError: If the dashboard server is unreachable.
        ValueError: If the dashboard rejects the credentials or request.
    """
    base_url = dashboard_url.rstrip("/")
    try:
        with httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
        ) as client:
            response = client.post(
                "/dashboard/auth/rotate-password",
                json={
                    "username": username,
                    "current_secret": current_secret.get_secret_value(),
                    "new_secret": new_secret.get_secret_value(),
                },
            )
    except httpx.HTTPError as exc:
        raise ConnectionError(f"Dashboard unreachable at {base_url}: {exc}") from exc

    if response.is_error:
        detail = _extract_error_detail(response)
        raise ValueError(
            f"Dashboard rejected password rotation (HTTP {response.status_code}): {detail}"
        )
    return f"Rotated password for '{username}' via {base_url}"


def _connect_oracle_adb() -> Any:
    """Open an Oracle ADB connection using HEXAQUEUE_ORACLE_ADB_* env vars."""
    if oracledb is None:
        raise RuntimeError(
            "oracledb is not installed; install hexaqueue-server[oracle] for ADB access"
        )
    kwargs: dict[str, Any] = {
        "user": os.environ.get("HEXAQUEUE_ORACLE_ADB_USER", "ADMIN"),
        "password": os.environ.get("HEXAQUEUE_ORACLE_ADB_PASSWORD", ""),
        "dsn": os.environ.get("HEXAQUEUE_ORACLE_ADB_DSN", ""),
    }
    wallet_dir = os.environ.get("HEXAQUEUE_ORACLE_ADB_WALLET_DIR")
    wallet_password = os.environ.get("HEXAQUEUE_ORACLE_ADB_WALLET_PASSWORD")
    if wallet_dir:
        kwargs["config_dir"] = wallet_dir
        kwargs["wallet_location"] = wallet_dir
        if wallet_password:
            kwargs["wallet_password"] = wallet_password
    return oracledb.connect(**kwargs)


def _rotate_in_sqlite(
    db_path: str,
    username: str,
    current_secret: SecretStr,
    new_secret: SecretStr,
    hasher: Pbkdf2PasswordHasher,
) -> str:
    """Verify current password and update PBKDF2 hash in local SQLite RBAC store."""
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT hashed_secret, is_active FROM hxq_rbac_principals WHERE principal_id = ?",
            (username,),
        ).fetchone()
        if row is None or not bool(row[1]):
            raise ValueError(f"Principal '{username}' not found or inactive.")
        if not hasher.verify_password(current_secret.get_secret_value(), str(row[0])):
            raise ValueError("Current password verification failed.")
        new_hash = hasher.hash_password(new_secret.get_secret_value())
        conn.execute(
            "UPDATE hxq_rbac_principals SET hashed_secret = ? WHERE principal_id = ?",
            (new_hash, username),
        )
        conn.commit()
    return f"Rotated password for '{username}' offline in SQLite ({db_path})"


def _rotate_in_oracle(
    username: str,
    current_secret: SecretStr,
    new_secret: SecretStr,
    hasher: Pbkdf2PasswordHasher,
) -> str:
    """Verify current password and update PBKDF2 hash in Oracle ADB RBAC store."""
    conn = _connect_oracle_adb()
    try:
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT hashed_secret, is_active FROM hxq_rbac_principals WHERE principal_id = :1",
                (username,),
            )
            row = cur.fetchone()
            if row is None or not bool(row[1]):
                raise ValueError(f"Principal '{username}' not found or inactive.")
            if not hasher.verify_password(
                current_secret.get_secret_value(), str(row[0])
            ):
                raise ValueError("Current password verification failed.")
            new_hash = hasher.hash_password(new_secret.get_secret_value())
            cur.execute(
                "UPDATE hxq_rbac_principals SET hashed_secret = :1 WHERE principal_id = :2",
                (new_hash, username),
            )
            conn.commit()
        finally:
            cur.close()
    finally:
        conn.close()
    return f"Rotated password for '{username}' offline in Oracle ADB"


def rotate_password_offline(
    username: str,
    current_secret: SecretStr,
    new_secret: SecretStr,
    *,
    sqlite_path: str | None = None,
) -> str:
    """Rotate a principal password directly in Oracle ADB or SQLite without HTTP.

    Args:
        username: Principal username to update.
        current_secret: Existing credential wrapped in SecretStr.
        new_secret: Replacement credential wrapped in SecretStr.
        sqlite_path: Optional explicit SQLite DB path override.

    Returns:
        Confirmation message describing the offline store updated.

    Raises:
        RuntimeError: If neither Oracle ADB nor SQLite RBAC storage is configured.
        ValueError: If principal is missing/inactive or current password is invalid.
    """
    hasher = Pbkdf2PasswordHasher()
    if os.environ.get("HEXAQUEUE_ORACLE_ADB_DSN"):
        return _rotate_in_oracle(username, current_secret, new_secret, hasher)
    resolved_sqlite = sqlite_path or os.environ.get("HEXAQUEUE_RBAC_DB_PATH")
    if resolved_sqlite:
        return _rotate_in_sqlite(
            resolved_sqlite, username, current_secret, new_secret, hasher
        )
    raise RuntimeError(
        "No offline RBAC store configured "
        "(set HEXAQUEUE_ORACLE_ADB_DSN or HEXAQUEUE_RBAC_DB_PATH)."
    )


def rotate_dashboard_password(
    username: str,
    current_secret: SecretStr,
    new_secret: SecretStr,
    *,
    dashboard_url: str | None = None,
    offline: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> str:
    """Rotate a dashboard principal password via HTTP with offline fallback.

    Args:
        username: Principal username to update.
        current_secret: Existing credential wrapped in SecretStr.
        new_secret: Replacement credential wrapped in SecretStr.
        dashboard_url: Optional dashboard URL (defaults to HEXAQUEUE_DASHBOARD_URL
            or http://127.0.0.1:8080).
        offline: If True, bypass HTTP and update Oracle ADB / SQLite directly.
        transport: Optional custom httpx transport for hermetic testing.

    Returns:
        Human-readable confirmation message without any secret values.
    """
    if offline:
        return rotate_password_offline(username, current_secret, new_secret)

    resolved_url = dashboard_url or os.environ.get(
        "HEXAQUEUE_DASHBOARD_URL",
        "http://127.0.0.1:8080",
    )
    try:
        return rotate_password_online(
            resolved_url,
            username,
            current_secret,
            new_secret,
            transport=transport,
        )
    except ConnectionError:
        return rotate_password_offline(username, current_secret, new_secret)


__all__ = [
    "rotate_dashboard_password",
    "rotate_password_offline",
    "rotate_password_online",
]
