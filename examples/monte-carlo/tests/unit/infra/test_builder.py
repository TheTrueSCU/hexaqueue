from pathlib import Path

from monte_carlo.infra.builder import build_monte_carlo_programmatic_pipeline


def test_build_monte_carlo_programmatic_pipeline(tmp_path: Path) -> None:
    """Verify programmatic pipeline construction produces valid RunSubmission."""
    submission = build_monte_carlo_programmatic_pipeline(
        run_id="test-prog-run",
        sim_dir=str(tmp_path / "test_mc_sim"),
        num_paths=20,
        steps=50,
    )

    assert submission.run_spec.id == "test-prog-run"
    assert len(submission.jobs) == 4  # 3 simulation regimes + 1 aggregate

    job_ids = {j.id for j in submission.jobs}
    assert job_ids == {
        "sim-regime-low_vol",
        "sim-regime-mid_vol",
        "sim-regime-high_vol",
        "smooth-and-aggregate",
    }

    # Verify group dependency expansion
    assert len(submission.dependencies["smooth-and-aggregate"]) == 3
    assert set(submission.dependencies["smooth-and-aggregate"]) == {
        "sim-regime-low_vol",
        "sim-regime-mid_vol",
        "sim-regime-high_vol",
    }
