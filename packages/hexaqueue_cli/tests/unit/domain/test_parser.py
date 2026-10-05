"""Tests for YAML pipeline parser with nested collections, inheritance, and parameter sweeps."""

from pathlib import Path

import pytest
import yaml

from hexaqueue_cli.domain.parser import (
    parse_run_spec_from_dict,
    parse_run_spec_from_file,
)


def test_parse_run_spec_valid(tmp_path: Path) -> None:
    """Verify parsing valid YAML pipeline definition."""
    data = {
        "run": {
            "id": "run-test-yaml",
            "name": "YAML Test Run",
            "tags": ["ci", "test"],
        },
        "jobs": [
            {
                "id": "step1",
                "name": "Download Data",
                "command": "echo 'downloading'",
                "resources": {"cpus": 2, "ram_mb": 1024},
            },
            {
                "id": "step2",
                "name": "Process Data",
                "command": "echo 'processing'",
                "depends_on": "step1",
            },
        ],
    }

    yaml_file = tmp_path / "pipeline.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    submission = parse_run_spec_from_file(yaml_file)
    assert submission.run_spec.id == "run-test-yaml"
    assert len(submission.jobs) == 2
    assert submission.dependencies["step2"] == ["step1"]


def test_parse_run_spec_with_nested_groups_and_matrix(tmp_path: Path) -> None:
    """Verify parsing nested groups with parameter inheritance and cartesian matrix sweep."""
    data = {
        "run": {
            "id": "matrix-pipeline",
            "name": "Matrix Pipeline",
            "env": {"BASE_DIR": "/tmp/data"},
            "resources": {"cpus": 1, "ram_mb": 512},
        },
        "groups": [
            {
                "id": "simulations",
                "name": "Simulation Sweep",
                "matrix": {
                    "regime": ["low", "high"],
                    "seed": [1, 2],
                },
                "resources": {"cpus": 2},
                "jobs": [
                    {
                        "id": "sim-{{ regime }}-{{ seed }}",
                        "name": "Simulate {{ regime }} #{{ seed }}",
                        "command": "python sim.py --regime {{ regime }} --seed {{ seed }} --dir {{ BASE_DIR }}",
                    }
                ],
            }
        ],
        "jobs": [
            {
                "id": "aggregate",
                "command": "python agg.py --dir {{ BASE_DIR }}",
                "depends_on": ["simulations"],
            }
        ],
    }

    yaml_file = tmp_path / "matrix_pipeline.yaml"
    with yaml_file.open("w") as f:
        yaml.safe_dump(data, f)

    submission = parse_run_spec_from_file(yaml_file)
    assert submission.run_spec.id == "matrix-pipeline"
    assert len(submission.jobs) == 5  # 4 matrix jobs + 1 aggregate job
    assert len(submission.dependencies["aggregate"]) == 4
    assert set(submission.dependencies["aggregate"]) == {
        "sim-low-1",
        "sim-low-2",
        "sim-high-1",
        "sim-high-2",
    }

    sim_job = next(j for j in submission.jobs if j.id == "sim-low-1")
    assert sim_job.resources.cpus == 2
    assert sim_job.resources.ram_mb == 512
    assert sim_job.env["BASE_DIR"] == "/tmp/data"


def test_parse_run_spec_missing_fields(tmp_path: Path) -> None:
    """Verify validation errors on invalid schemas."""
    with pytest.raises(ValueError, match="must contain a 'run' object"):
        parse_run_spec_from_dict({})

    with pytest.raises(ValueError, match="Run 'id' is required"):
        parse_run_spec_from_dict({"run": {}})

    with pytest.raises(
        ValueError, match="must contain a non-empty 'jobs' or 'groups' list"
    ):
        parse_run_spec_from_dict({"run": {"id": "r1"}, "jobs": []})

    with pytest.raises(ValueError, match="Job 'id' is required"):
        parse_run_spec_from_dict({"run": {"id": "r1"}, "jobs": [{}]})

    with pytest.raises(ValueError, match="must specify a 'command'"):
        parse_run_spec_from_dict({"run": {"id": "r1"}, "jobs": [{"id": "j1"}]})

    with pytest.raises(ValueError, match="Group 'id' is required"):
        parse_run_spec_from_dict({"run": {"id": "r1"}, "groups": [{}]})

    with pytest.raises(FileNotFoundError):
        parse_run_spec_from_file(tmp_path / "non_existent.yaml")

    non_dict_file = tmp_path / "list.yaml"
    with non_dict_file.open("w") as f:
        f.write("- item1\n- item2\n")

    with pytest.raises(ValueError, match="top-level YAML mapping"):
        parse_run_spec_from_file(non_dict_file)
