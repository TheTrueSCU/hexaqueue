"""Tests for JobGroupSpec, parameter inheritance, and matrix expansion engine."""

import pytest

from hexaqueue_core.domain.group import (
    GroupExpansionEngine,
    JobGroupSpec,
    JobTemplateSpec,
    ResourceOverrideSpec,
)
from hexaqueue_core.domain.resources import ResourceRequirements


def test_resource_override_spec():
    """Verify ResourceOverrideSpec applies partial overrides to base requirements."""
    base = ResourceRequirements(
        cpus=2, ram_mb=1024, scratch_mb=500, walltime_seconds=60
    )
    override = ResourceOverrideSpec(cpus=4, walltime_seconds=120)
    merged = override.apply_to(base)

    assert merged.cpus == 4
    assert merged.ram_mb == 1024
    assert merged.scratch_mb == 500
    assert merged.walltime_seconds == 120


def test_job_template_validation():
    """Verify JobTemplateSpec requires valid non-empty id and command."""
    with pytest.raises(ValueError, match="Job template 'id' cannot be empty"):
        JobTemplateSpec(id="   ", command="echo 1")

    with pytest.raises(ValueError, match="Job template 'command' cannot be empty"):
        JobTemplateSpec(id="j1", command="   ")


def test_job_group_validation():
    """Verify JobGroupSpec validation rules."""
    with pytest.raises(ValueError, match="Group 'id' cannot be empty"):
        JobGroupSpec(id="   ")

    with pytest.raises(ValueError, match="cannot specify both 'matrix' and 'params'"):
        JobGroupSpec(
            id="g1",
            matrix={"a": [1, 2]},
            params=[{"a": 1}],
        )


def test_group_expansion_matrix_cartesian_product():
    """Verify multidimensional matrix cartesian expansion and parameter substitution."""
    engine = GroupExpansionEngine(run_id="run-mc")

    group = JobGroupSpec(
        id="sim-regimes",
        matrix={
            "regime": ["low", "high"],
            "seed": [10, 20],
        },
        env={"COMMON_ENV": "root_val", "REGIME": "{{ regime }}"},
        tags=["simulation"],
        resources=ResourceOverrideSpec(cpus=2),
        jobs=[
            JobTemplateSpec(
                id="sim-{{ regime }}-{{ seed }}",
                name="Simulate {{ regime }} (Seed {{ seed }})",
                command="python sim.py --regime {{ regime }} --seed {{ seed }}",
                tags=["worker"],
                collateral_ids=["bundle-{{ regime }}"],
            )
        ],
    )

    resolved = engine.expand_groups(groups=[group])

    assert len(resolved.jobs) == 4
    job_ids = [j.id for j in resolved.jobs]
    assert job_ids == [
        "sim-low-10",
        "sim-low-20",
        "sim-high-10",
        "sim-high-20",
    ]

    j_low_10 = next(j for j in resolved.jobs if j.id == "sim-low-10")
    assert j_low_10.name == "Simulate low (Seed 10)"
    assert j_low_10.command == "python sim.py --regime low --seed 10"
    assert j_low_10.env["COMMON_ENV"] == "root_val"
    assert j_low_10.env["REGIME"] == "low"
    assert j_low_10.resources.cpus == 2
    assert j_low_10.tags == ["simulation", "worker"]
    assert j_low_10.collateral_ids == ["bundle-low"]


def test_group_expansion_arbitrary_recursive_nesting():
    """Verify arbitrary nested groups inherit env, tags, and resources with child overrides."""
    engine = GroupExpansionEngine(run_id="nested-run")

    parent_group = JobGroupSpec(
        id="parent-stage",
        env={"STAGE": "parent", "GLOBAL": "1"},
        tags=["parent-tag"],
        resources=ResourceOverrideSpec(cpus=2, ram_mb=2048),
        groups=[
            JobGroupSpec(
                id="child-stage",
                env={"STAGE": "child", "EXTRA": "2"},
                tags=["child-tag"],
                resources=ResourceOverrideSpec(ram_mb=4096),
                jobs=[
                    JobTemplateSpec(
                        id="child-leaf",
                        command="echo child",
                    )
                ],
            )
        ],
    )

    resolved = engine.expand_groups(groups=[parent_group])
    assert len(resolved.jobs) == 1
    leaf = resolved.jobs[0]
    assert leaf.id == "child-leaf"
    assert leaf.env == {"STAGE": "child", "GLOBAL": "1", "EXTRA": "2"}
    assert leaf.tags == ["parent-tag", "child-tag"]
    assert leaf.resources.cpus == 2
    assert leaf.resources.ram_mb == 4096


def test_group_expansion_group_level_dependencies():
    """Verify depending on a group ID expands dependencies to all constituent jobs in that group."""
    engine = GroupExpansionEngine(run_id="dep-run")

    producer_group = JobGroupSpec(
        id="producers",
        params=[
            {"part": "A"},
            {"part": "B"},
        ],
        jobs=[
            JobTemplateSpec(
                id="prod-{{ part }}",
                command="produce {{ part }}",
            )
        ],
    )

    consumer_job = JobTemplateSpec(
        id="consumer",
        command="consume all",
        depends_on=["producers"],
    )

    resolved = engine.expand_groups(
        groups=[producer_group],
        top_level_jobs=[consumer_job],
    )

    assert len(resolved.jobs) == 3
    assert set(resolved.dependencies["consumer"]) == {"prod-A", "prod-B"}


def test_group_expansion_duplicate_id_fails():
    """Verify duplicate job IDs raise ValueError."""
    engine = GroupExpansionEngine(run_id="dup-run")

    group = JobGroupSpec(
        id="g1",
        jobs=[
            JobTemplateSpec(id="duplicate", command="echo 1"),
            JobTemplateSpec(id="duplicate", command="echo 2"),
        ],
    )

    with pytest.raises(ValueError, match="Duplicate job ID 'duplicate' generated"):
        engine.expand_groups(groups=[group])


def test_group_expansion_unresolvable_dependency_fails():
    """Verify unresolvable dependency references raise ValueError."""
    engine = GroupExpansionEngine(run_id="bad-dep-run")

    group = JobGroupSpec(
        id="g1",
        jobs=[
            JobTemplateSpec(
                id="j1",
                command="echo 1",
                depends_on=["non_existent_group_or_job"],
            )
        ],
    )

    with pytest.raises(ValueError, match="cannot be resolved"):
        engine.expand_groups(groups=[group])


def test_group_expansion_empty_matrix_and_params():
    """Verify expansion with empty matrix and empty params (single execution)."""
    engine = GroupExpansionEngine(run_id="simple-run")
    group = JobGroupSpec(
        id="simple-group",
        jobs=[JobTemplateSpec(id="j1", command="echo hello")],
    )
    resolved = engine.expand_groups(groups=[group])
    assert len(resolved.jobs) == 1
    assert resolved.jobs[0].id == "j1"


def test_job_template_env_interpolation():
    """Verify template env variables interpolate properly and become available in command."""
    engine = GroupExpansionEngine(run_id="env-interp")
    group = JobGroupSpec(
        id="env-grp",
        env={"ROOT": "/var/app"},
        jobs=[
            JobTemplateSpec(
                id="j1",
                env={"OUTPUT_PATH": "{{ ROOT }}/out.log"},
                command="write --path {{ OUTPUT_PATH }}",
            )
        ],
    )
    resolved = engine.expand_groups(groups=[group])
    assert resolved.jobs[0].env["OUTPUT_PATH"] == "/var/app/out.log"
    assert resolved.jobs[0].command == "write --path /var/app/out.log"
