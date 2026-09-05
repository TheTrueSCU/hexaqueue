"""YAML and dictionary pipeline parser for CLI run submissions.

Notes/Architectural Intent:
    Translates user-provided declarative YAML run definitions (supporting top-level jobs,
    hierarchical nested groups, matrix/params parameter sweeps, and dependency resolution)
    into structured RunSubmission specifications conforming to hexaqueue domain models.
"""

from pathlib import Path
from typing import Any

import yaml

from hexaqueue_core.domain.group import (
    GroupExpansionEngine,
    JobGroupSpec,
    JobTemplateSpec,
    ResourceOverrideSpec,
)
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.domain.models import RunSubmission


def _parse_resource_override(
    res_data: dict[str, Any] | None,
) -> ResourceOverrideSpec | None:
    """Parse dictionary into ResourceOverrideSpec if present."""
    if not res_data:
        return None
    return ResourceOverrideSpec(
        cpus=res_data.get("cpus"),
        ram_mb=res_data.get("ram_mb"),
        gpus=res_data.get("gpus"),
        gpu_model=res_data.get("gpu_model"),
        vram_mb=res_data.get("vram_mb"),
        scratch_mb=res_data.get("scratch_mb"),
        walltime_seconds=res_data.get("walltime_seconds"),
    )


def _parse_job_template(data: dict[str, Any]) -> JobTemplateSpec:
    """Parse dictionary into JobTemplateSpec."""
    j_id = data.get("id")
    if not j_id:
        msg = "Job 'id' is required"
        raise ValueError(msg)

    cmd = data.get("command")
    if not cmd:
        msg = f"Job '{j_id}' must specify a 'command'"
        raise ValueError(msg)

    deps = data.get("depends_on", [])
    if isinstance(deps, str):
        deps = [deps]

    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    collateral = data.get("collateral_ids", [])
    if isinstance(collateral, str):
        collateral = [collateral]

    return JobTemplateSpec(
        id=j_id,
        name=data.get("name"),
        command=cmd,
        args=data.get("args", []),
        env=data.get("env", {}),
        resources=_parse_resource_override(data.get("resources")),
        tags=tags,
        depends_on=deps,
        collateral_ids=collateral,
    )


def _parse_group_spec(data: dict[str, Any]) -> JobGroupSpec:
    """Recursively parse nested group dictionaries into JobGroupSpec instances."""
    g_id = data.get("id")
    if not g_id:
        msg = "Group 'id' is required"
        raise ValueError(msg)

    deps = data.get("depends_on", [])
    if isinstance(deps, str):
        deps = [deps]

    tags = data.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    raw_jobs = data.get("jobs", [])
    jobs = (
        [_parse_job_template(j) for j in raw_jobs] if isinstance(raw_jobs, list) else []
    )

    raw_groups = data.get("groups", [])
    groups = (
        [_parse_group_spec(g) for g in raw_groups]
        if isinstance(raw_groups, list)
        else []
    )

    return JobGroupSpec(
        id=g_id,
        name=data.get("name"),
        matrix=data.get("matrix", {}),
        params=data.get("params", []),
        env=data.get("env", {}),
        resources=_parse_resource_override(data.get("resources")),
        tags=tags,
        depends_on=deps,
        jobs=jobs,
        groups=groups,
    )


def parse_run_spec_from_dict(data: dict[str, Any]) -> RunSubmission:
    """Parse RunSubmission from a dictionary representation.

    Supports top-level 'jobs', hierarchical 'groups', matrix sweeps, and parameter inheritance.

    Args:
        data: Dictionary conforming to pipeline run spec schema.

    Returns:
        RunSubmission instance.

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    if "run" not in data or not isinstance(data["run"], dict):
        msg = "Pipeline specification must contain a 'run' object"
        raise ValueError(msg)

    run_dict = data["run"]
    run_id = run_dict.get("id")
    if not run_id:
        msg = "Run 'id' is required"
        raise ValueError(msg)

    tags = run_dict.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    run_spec = RunSpec(
        id=run_id,
        name=run_dict.get("name", run_id),
        tags=tags,
    )

    jobs_data = data.get("jobs", [])
    groups_data = data.get("groups", [])

    if not jobs_data and not groups_data:
        msg = "Pipeline specification must contain a non-empty 'jobs' or 'groups' list"
        raise ValueError(msg)

    parsed_top_jobs: list[JobTemplateSpec] = []
    if isinstance(jobs_data, list):
        for j_data in jobs_data:
            parsed_top_jobs.append(_parse_job_template(j_data))

    parsed_groups: list[JobGroupSpec] = []
    if isinstance(groups_data, list):
        for g_data in groups_data:
            parsed_groups.append(_parse_group_spec(g_data))

    global_env = run_dict.get("env", {})
    global_resources = _parse_resource_override(run_dict.get("resources"))

    expansion_engine = GroupExpansionEngine(run_id=run_id)
    resolved = expansion_engine.expand_groups(
        groups=parsed_groups,
        top_level_jobs=parsed_top_jobs,
        global_env=global_env,
        global_tags=tags,
        global_resources=global_resources,
    )

    if not resolved.jobs:
        msg = "Pipeline specification produced 0 executable jobs"
        raise ValueError(msg)

    return RunSubmission(
        run_spec=run_spec,
        jobs=resolved.jobs,
        dependencies=resolved.dependencies,
    )


def parse_run_spec_from_file(file_path: str | Path) -> RunSubmission:
    """Parse RunSubmission from a YAML or JSON file.

    Args:
        file_path: Path to the pipeline definition file.

    Returns:
        RunSubmission instance.

    Raises:
        FileNotFoundError: If file does not exist.
        ValueError: If file content is invalid.
    """
    path = Path(file_path)
    if not path.is_file():
        msg = f"File not found: {path}"
        raise FileNotFoundError(msg)

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        msg = "Pipeline file must contain a top-level YAML mapping"
        raise ValueError(msg)

    return parse_run_spec_from_dict(data)


__all__ = [
    "parse_run_spec_from_dict",
    "parse_run_spec_from_file",
]
