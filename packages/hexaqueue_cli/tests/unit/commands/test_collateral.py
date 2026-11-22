"""Unit tests for hq collateral CLI commands."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def setup_session() -> None:
    """Hermetic session fixture."""
    session = LocalCliSession(concurrency=2)
    set_default_session(session)


def test_cli_collateral_push_command(tmp_path: Path) -> None:
    """Verify hq collateral push computes digest and stages bundle."""
    test_file = tmp_path / "model_weights.bin"
    test_file.write_bytes(b"mock weight parameters content")

    res = runner.invoke(
        app,
        [
            "collateral",
            "push",
            str(test_file),
            "--name",
            "model_weights.bin",
            "--tier",
            "PERMANENT",
            "--kind",
            "TEST_BINARY",
        ],
    )
    assert res.exit_code == 0
    assert "Collateral staged successfully" in res.stdout
    assert "model_weights.bin" in res.stdout
    assert "PERMANENT" in res.stdout


def test_cli_collateral_full_lifecycle(tmp_path: Path) -> None:
    """Verify list, inspect, pin, unpin, promote, evict, and delete CLI subcommands."""
    test_file = tmp_path / "dataset.bin"
    test_file.write_bytes(b"dataset-bytes-payload")

    push_res = runner.invoke(
        app,
        [
            "collateral",
            "stage",
            str(test_file),
            "--user",
            "alice",
            "--ttl",
            "3600",
        ],
    )
    assert push_res.exit_code == 0

    # List as alice -> sees bundle
    list_res = runner.invoke(
        app, ["collateral", "list", "--user", "alice", "-f", "json"]
    )
    assert list_res.exit_code == 0
    items = json.loads(list_res.stdout)
    assert len(items) == 1
    col_id = items[0]["id"]
    assert items[0]["owner"] == "alice"

    # List as bob without --admin -> isolated empty list
    bob_res = runner.invoke(app, ["collateral", "list", "--user", "bob", "-f", "json"])
    assert bob_res.exit_code == 0
    assert json.loads(bob_res.stdout) == []

    # List as bob with --admin -> sees all
    admin_res = runner.invoke(
        app, ["collateral", "list", "--user", "bob", "--admin", "-f", "table"]
    )
    assert admin_res.exit_code == 0
    assert col_id in admin_res.stdout

    # Inspect
    inspect_res = runner.invoke(
        app, ["collateral", "inspect", col_id, "--user", "alice", "-f", "json"]
    )
    assert inspect_res.exit_code == 0
    inspected = json.loads(inspect_res.stdout)
    assert inspected["id"] == col_id

    # Pin & unpin
    pin_res = runner.invoke(
        app, ["collateral", "pin", col_id, "--user", "alice", "-f", "json"]
    )
    assert pin_res.exit_code == 0
    assert json.loads(pin_res.stdout)["active_pin_count"] == 1

    unpin_res = runner.invoke(
        app, ["collateral", "unpin", col_id, "--user", "alice", "-f", "json"]
    )
    assert unpin_res.exit_code == 0
    assert json.loads(unpin_res.stdout)["active_pin_count"] == 0

    # Promote without --admin -> denied
    promote_denied = runner.invoke(
        app, ["collateral", "promote", col_id, "--user", "alice"]
    )
    assert promote_denied.exit_code == 1

    # Promote with --admin -> succeeds
    promote_ok = runner.invoke(
        app,
        ["collateral", "promote", col_id, "--user", "alice", "--admin", "-f", "json"],
    )
    assert promote_ok.exit_code == 0
    assert json.loads(promote_ok.stdout)["tier"] == "PERMANENT"

    # Evict (non-empty / json mode works cleanly)
    evict_res = runner.invoke(
        app,
        ["collateral", "evict", "--max-age", "10", "--user", "alice", "-f", "json"],
    )
    assert evict_res.exit_code == 0
    assert isinstance(json.loads(evict_res.stdout), list)

    # Delete PERMANENT requires --admin
    del_denied = runner.invoke(app, ["collateral", "delete", col_id, "--user", "alice"])
    assert del_denied.exit_code == 1

    del_ok = runner.invoke(
        app, ["collateral", "delete", col_id, "--user", "alice", "--admin"]
    )
    assert del_ok.exit_code == 0
    assert col_id in del_ok.stdout
