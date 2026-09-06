"""Tests for Monte-Carlo collateral runner CLI."""

from pathlib import Path

import pytest

from monte_carlo.cli import main, run_aggregate, run_simulate


def test_simulate_creates_valid_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify simulate subcommand generates path JSON output file."""
    out_dir = tmp_path / "mc_out"
    run_simulate(
        regime="test_regime",
        seed=42,
        drift=0.05,
        vol=0.20,
        num_paths=10,
        steps=20,
        dt=0.01,
        initial_value=100.0,
        output_dir=out_dir,
    )

    out_file = out_dir / "test_regime.json"
    assert out_file.is_file()

    captured = capsys.readouterr()
    assert "Simulated test_regime" in captured.out


def test_aggregate_merges_and_smooths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Verify aggregate subcommand computes smoothed surface from simulations."""
    out_dir = tmp_path / "mc_out"
    run_simulate(
        regime="r1",
        seed=1,
        drift=0.03,
        vol=0.10,
        num_paths=10,
        steps=20,
        dt=0.01,
        initial_value=100.0,
        output_dir=out_dir,
    )
    run_simulate(
        regime="r2",
        seed=2,
        drift=0.08,
        vol=0.30,
        num_paths=10,
        steps=20,
        dt=0.01,
        initial_value=100.0,
        output_dir=out_dir,
    )

    run_aggregate(input_dir=out_dir, regimes=["r1", "r2"], window_size=3)
    captured = capsys.readouterr()
    assert "Monte-Carlo Aggregation Complete" in captured.out
    assert "Total Paths: 20" in captured.out


def test_aggregate_missing_file_raises(tmp_path: Path) -> None:
    """Verify FileNotFoundError raised when simulation output is missing."""
    with pytest.raises(FileNotFoundError, match="Missing expected regime simulation"):
        run_aggregate(input_dir=tmp_path, regimes=["non_existent"], window_size=3)


def test_main_cli_dispatch(tmp_path: Path) -> None:
    """Verify CLI main parses arguments and executes subcommands."""
    out_dir = tmp_path / "cli_out"
    rc_sim = main(
        [
            "simulate",
            "--regime",
            "low_vol",
            "--seed",
            "101",
            "--drift",
            "0.03",
            "--vol",
            "0.08",
            "--paths",
            "10",
            "--steps",
            "15",
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc_sim == 0
    assert (out_dir / "low_vol.json").is_file()

    rc_agg = main(
        [
            "aggregate",
            "--input-dir",
            str(out_dir),
            "--regimes",
            "low_vol",
            "--window",
            "3",
        ]
    )
    assert rc_agg == 0
