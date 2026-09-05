"""YAML and dictionary pipeline parser for CLI run submissions.

Notes/Architectural Intent:
    Translates user-provided declarative YAML run definitions into structured
    RunSubmission specifications conforming to hexaqueue domain models.
"""

from pathlib import Path
from typing import Any

import yaml

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.domain.models import RunSubmission


def parse_run_spec_from_dict(data: dict[str, Any]) -> RunSubmission:
    """Parse RunSubmission from a dictionary representation.

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
    if not jobs_data or not isinstance(jobs_data, list):
        msg = "Pipeline specification must contain a non-empty 'jobs' list"
        raise ValueError(msg)

    jobs: list[JobSpec] = []
    dependencies: dict[str, list[str]] = {}

    for j_data in jobs_data:
        j_id = j_data.get("id")
        if not j_id:
            msg = "Job 'id' is required"
            raise ValueError(msg)

        cmd = j_data.get("command")
        if not cmd:
            msg = f"Job '{j_id}' must specify a 'command'"
            raise ValueError(msg)

        res_data = j_data.get("resources", {})
        resources = ResourceRequirements(
            cpus=res_data.get("cpus", 1),
            ram_mb=res_data.get("ram_mb", 512),
            gpus=res_data.get("gpus", 0),
            gpu_model=res_data.get("gpu_model"),
            scratch_mb=res_data.get("scratch_mb", 1024),
            walltime_seconds=res_data.get("walltime_seconds", 300),
        )

        j_tags = j_data.get("tags", [])
        if isinstance(j_tags, str):
            j_tags = [j_tags]

        job = JobSpec(
            id=j_id,
            run_id=run_id,
            name=j_data.get("name", j_id),
            command=cmd,
            args=j_data.get("args", []),
            env=j_data.get("env", {}),
            resources=resources,
            tags=j_tags,
        )
        jobs.append(job)

        if "depends_on" in j_data:
            deps = j_data["depends_on"]
            if isinstance(deps, str):
                deps = [deps]
            dependencies[j_id] = deps

    return RunSubmission(
        run_spec=run_spec,
        jobs=jobs,
        dependencies=dependencies,
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
