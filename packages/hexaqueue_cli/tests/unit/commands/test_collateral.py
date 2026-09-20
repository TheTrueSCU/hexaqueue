"""Unit tests for hq collateral CLI commands."""

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
