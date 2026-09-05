"""Hierarchical Job Group collections, parameter inheritance, and matrix expansions.

Notes/Architectural Intent:
    Provides arbitrary recursive nesting of job collections (JobGroupSpec),
    parameter inheritance (env variables, tags, resource overrides, templating variables),
    and multidimensional sequence/matrix expansions (cartesian product or zipped parameters)
    which resolve deterministically into flattened JobSpec instances and dependency graphs.
"""

import itertools
import re
from collections.abc import Sequence
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements


def _interpolate_string(template_str: str, context: dict[str, Any]) -> str:
    """Interpolate {{ var }} placeholders in string using context dictionary.

    Args:
        template_str: String containing optional {{ var }} expressions.
        context: Key-value dictionary providing interpolation variables.

    Returns:
        Interpolated string.
    """
    if "{{" not in template_str:
        return template_str

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1).strip()
        if key in context:
            return str(context[key])
        return match.group(0)

    return re.sub(r"\{\{\s*([a-zA-Z0-9_\.\-]+)\s*\}\}", _repl, template_str)


class ResourceOverrideSpec(BaseModel):
    """Partial resource requirement overrides for hierarchical inheritance.

    Args:
        cpus: Optional CPU core count.
        ram_mb: Optional RAM in MB.
        gpus: Optional GPU count.
        gpu_model: Optional GPU model architecture string.
        vram_mb: Optional GPU VRAM in MB.
        scratch_mb: Optional scratch disk in MB.
        walltime_seconds: Optional walltime limit in seconds.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cpus: int | None = Field(default=None, ge=1)
    ram_mb: int | None = Field(default=None, ge=128)
    gpus: int | None = Field(default=None, ge=0)
    gpu_model: str | None = Field(default=None)
    vram_mb: int | None = Field(default=None, ge=0)
    scratch_mb: int | None = Field(default=None, ge=0)
    walltime_seconds: int | None = Field(default=None, ge=10)

    def apply_to(self, base: ResourceRequirements) -> ResourceRequirements:
        """Merge overrides on top of a base ResourceRequirements instance.

        Args:
            base: Base resource requirements to inherit from.

        Returns:
            A new ResourceRequirements instance with overrides applied.
        """
        return ResourceRequirements(
            cpus=self.cpus if self.cpus is not None else base.cpus,
            ram_mb=self.ram_mb if self.ram_mb is not None else base.ram_mb,
            gpus=self.gpus if self.gpus is not None else base.gpus,
            gpu_model=self.gpu_model if self.gpu_model is not None else base.gpu_model,
            vram_mb=self.vram_mb if self.vram_mb is not None else base.vram_mb,
            scratch_mb=(
                self.scratch_mb if self.scratch_mb is not None else base.scratch_mb
            ),
            walltime_seconds=(
                self.walltime_seconds
                if self.walltime_seconds is not None
                else base.walltime_seconds
            ),
        )


class JobTemplateSpec(BaseModel):
    """Declarative specification for a job template subject to parameter interpolation.

    Args:
        id: Unique job identifier or parameterized template (e.g. 'sim-{{ regime }}').
        name: Human-readable job name template.
        command: Executable command string or template.
        args: List of command arguments or templates.
        env: Job-level environment variables.
        resources: Specific resource requirements or overrides.
        tags: Job-level tags.
        depends_on: List of upstream job or group IDs this job depends upon.
        collateral_ids: Associated collateral bundle IDs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique job identifier template")
    name: str | None = Field(default=None, description="Job name template")
    command: str = Field(description="Executable command template")
    args: list[str] = Field(default_factory=list, description="Command arguments")
    env: dict[str, str] = Field(
        default_factory=dict, description="Environment variables"
    )
    resources: ResourceOverrideSpec | None = Field(
        default=None, description="Resource overrides"
    )
    tags: list[str] = Field(default_factory=list, description="Job tags")
    depends_on: list[str] = Field(
        default_factory=list, description="Upstream dependencies"
    )
    collateral_ids: list[str] = Field(
        default_factory=list, description="Collateral bundle IDs"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate template invariants."""
        if not self.id.strip():
            msg = "Job template 'id' cannot be empty"
            raise ValueError(msg)
        if not self.command.strip():
            msg = "Job template 'command' cannot be empty"
            raise ValueError(msg)
        return self


class JobGroupSpec(BaseModel):
    """Hierarchical collection of jobs and nested groups sharing scoped parameters.

    Args:
        id: Unique identifier for this group scope.
        name: Human-readable group name.
        matrix: Cartesian product parameter sweep dictionary.
        params: Explicit list of parameter combination dictionaries.
        env: Inherited environment variables defined at this group level.
        resources: Inherited resource overrides applied to all children.
        tags: Inherited metadata tags applied to all children.
        depends_on: Upstream dependencies required before any job in this group can execute.
        jobs: List of constituent job templates directly inside this group.
        groups: List of nested child JobGroupSpec instances (arbitrary depth).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique group identifier")
    name: str | None = Field(default=None, description="Human readable group name")
    matrix: dict[str, list[Any]] = Field(
        default_factory=dict,
        description="Cartesian product matrix variables mapping name to sequence of values",
    )
    params: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Explicit sequence of parameter dictionaries",
    )
    env: dict[str, str] = Field(
        default_factory=dict, description="Group scoped environment variables"
    )
    resources: ResourceOverrideSpec | None = Field(
        default=None, description="Group scoped resource defaults"
    )
    tags: list[str] = Field(default_factory=list, description="Group scoped tags")
    depends_on: list[str] = Field(
        default_factory=list, description="Dependencies for entire group"
    )
    jobs: list[JobTemplateSpec] = Field(
        default_factory=list, description="Constituent job templates in group"
    )
    groups: list["JobGroupSpec"] = Field(
        default_factory=list, description="Nested child groups"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate group invariants."""
        if not self.id.strip():
            msg = "Group 'id' cannot be empty"
            raise ValueError(msg)
        if self.matrix and self.params:
            msg = f"Group '{self.id}' cannot specify both 'matrix' and 'params' simultaneously"
            raise ValueError(msg)
        return self


class ResolvedJobCollection(BaseModel):
    """Flattened collection of concrete JobSpecs, dependency graph, and group mappings.

    Args:
        jobs: List of flattened, concrete JobSpec instances.
        dependencies: Adjacency map from child job_id -> list of prerequisite parent job_ids.
        group_job_map: Mapping from group ID -> set of constituent leaf job IDs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    jobs: list[JobSpec] = Field(description="Flattened list of concrete jobs")
    dependencies: dict[str, list[str]] = Field(
        default_factory=dict, description="Job-to-job dependency mappings"
    )
    group_job_map: dict[str, list[str]] = Field(
        default_factory=dict, description="Mapping of group ID to leaf job IDs"
    )


class GroupExpansionEngine:
    """Engine for recursively expanding nested job groups with inheritance into flattened DAGs.

    Notes/Architectural Intent:
        Performs lexical and parameter scope propagation, matrix expansion,
        template variable substitution, and group-level dependency linking.
    """

    def __init__(
        self, run_id: str, default_resources: ResourceRequirements | None = None
    ) -> None:
        """Initialize expansion engine for a specific run.

        Args:
            run_id: Root run identifier.
            default_resources: Base resource requirements for all jobs unless overridden.
        """
        self._run_id = run_id
        self._default_resources = default_resources or ResourceRequirements()

    def expand_groups(
        self,
        groups: Sequence[JobGroupSpec],
        top_level_jobs: Sequence[JobTemplateSpec] | None = None,
        global_env: dict[str, str] | None = None,
        global_tags: list[str] | None = None,
        global_resources: ResourceOverrideSpec | None = None,
    ) -> ResolvedJobCollection:
        """Expand all top-level jobs and recursive groups into a concrete ResolvedJobCollection.

        Args:
            groups: Top-level sequence of JobGroupSpec instances.
            top_level_jobs: Optional sequence of top-level JobTemplateSpecs outside groups.
            global_env: Optional global environment variables.
            global_tags: Optional global tags.
            global_resources: Optional global resource overrides.

        Returns:
            ResolvedJobCollection containing flattened jobs, dependencies, and group index.

        Raises:
            ValueError: If duplicate job IDs are generated or invalid dependencies exist.
        """
        accumulated_jobs: list[JobSpec] = []
        raw_dependencies: dict[str, list[str]] = {}
        group_job_map: dict[str, list[str]] = {}

        base_res = (
            global_resources.apply_to(self._default_resources)
            if global_resources
            else self._default_resources
        )
        base_env = dict(global_env or {})
        base_tags = list(global_tags or [])
        base_context: dict[str, Any] = {}

        if top_level_jobs:
            for job_tmpl in top_level_jobs:
                job_spec, deps = self._resolve_job_template(
                    tmpl=job_tmpl,
                    inherited_env=base_env,
                    inherited_tags=base_tags,
                    inherited_resources=base_res,
                    context=base_context,
                    inherited_group_deps=[],
                )
                accumulated_jobs.append(job_spec)
                if deps:
                    raw_dependencies[job_spec.id] = deps

        for grp in groups:
            self._expand_group_recursive(
                group=grp,
                inherited_env=base_env,
                inherited_tags=base_tags,
                inherited_resources=base_res,
                context=base_context,
                inherited_group_deps=[],
                accumulated_jobs=accumulated_jobs,
                raw_dependencies=raw_dependencies,
                group_job_map=group_job_map,
            )

        seen_job_ids: set[str] = set()
        for job in accumulated_jobs:
            if job.id in seen_job_ids:
                msg = f"Duplicate job ID '{job.id}' generated during group expansion"
                raise ValueError(msg)
            seen_job_ids.add(job.id)

        resolved_dependencies = self._resolve_dependency_references(
            raw_dependencies=raw_dependencies,
            group_job_map=group_job_map,
            all_job_ids=seen_job_ids,
        )

        return ResolvedJobCollection(
            jobs=accumulated_jobs,
            dependencies=resolved_dependencies,
            group_job_map=group_job_map,
        )

    def _expand_group_recursive(
        self,
        group: JobGroupSpec,
        inherited_env: dict[str, str],
        inherited_tags: list[str],
        inherited_resources: ResourceRequirements,
        context: dict[str, Any],
        inherited_group_deps: list[str],
        accumulated_jobs: list[JobSpec],
        raw_dependencies: dict[str, list[str]],
        group_job_map: dict[str, list[str]],
    ) -> list[str]:
        """Recursively process a group, expanding its matrix/params and child elements.

        Returns:
            List of concrete leaf job IDs generated within this group scope.
        """
        curr_env = {**inherited_env, **group.env}
        curr_tags = list(dict.fromkeys(inherited_tags + group.tags))
        curr_resources = (
            group.resources.apply_to(inherited_resources)
            if group.resources
            else inherited_resources
        )
        curr_group_deps = list(dict.fromkeys(inherited_group_deps + group.depends_on))

        param_contexts = self._build_param_contexts(group.matrix, group.params)
        all_created_job_ids: list[str] = []

        for p_ctx in param_contexts:
            scoped_context = {**context, **p_ctx}
            interpolated_env = {
                k: _interpolate_string(v, scoped_context) for k, v in curr_env.items()
            }

            for job_tmpl in group.jobs:
                job_spec, deps = self._resolve_job_template(
                    tmpl=job_tmpl,
                    inherited_env=interpolated_env,
                    inherited_tags=curr_tags,
                    inherited_resources=curr_resources,
                    context=scoped_context,
                    inherited_group_deps=curr_group_deps,
                )
                accumulated_jobs.append(job_spec)
                all_created_job_ids.append(job_spec.id)
                if deps:
                    raw_dependencies[job_spec.id] = deps

            for child_group in group.groups:
                child_job_ids = self._expand_group_recursive(
                    group=child_group,
                    inherited_env=interpolated_env,
                    inherited_tags=curr_tags,
                    inherited_resources=curr_resources,
                    context=scoped_context,
                    inherited_group_deps=curr_group_deps,
                    accumulated_jobs=accumulated_jobs,
                    raw_dependencies=raw_dependencies,
                    group_job_map=group_job_map,
                )
                all_created_job_ids.extend(child_job_ids)

        group_job_map.setdefault(group.id, []).extend(all_created_job_ids)
        return all_created_job_ids

    def _resolve_job_template(
        self,
        tmpl: JobTemplateSpec,
        inherited_env: dict[str, str],
        inherited_tags: list[str],
        inherited_resources: ResourceRequirements,
        context: dict[str, Any],
        inherited_group_deps: list[str],
    ) -> tuple[JobSpec, list[str]]:
        """Interpolate and construct a concrete JobSpec from a JobTemplateSpec."""
        full_context = {**inherited_env, **context}
        job_id = _interpolate_string(tmpl.id, full_context)
        job_name = _interpolate_string(tmpl.name or tmpl.id, full_context)

        job_env = {**inherited_env}
        for k, v in tmpl.env.items():
            job_env[k] = _interpolate_string(v, full_context)

        job_context = {**full_context, **job_env}
        job_command = _interpolate_string(tmpl.command, job_context)
        job_args = [_interpolate_string(arg, job_context) for arg in tmpl.args]

        job_tags = list(dict.fromkeys(inherited_tags + tmpl.tags))
        job_resources = (
            tmpl.resources.apply_to(inherited_resources)
            if tmpl.resources
            else inherited_resources
        )
        collateral_ids = [_interpolate_string(c, context) for c in tmpl.collateral_ids]

        raw_deps = list(
            dict.fromkeys(
                inherited_group_deps
                + [_interpolate_string(d, context) for d in tmpl.depends_on]
            )
        )

        job = JobSpec(
            id=job_id,
            run_id=self._run_id,
            name=job_name,
            command=job_command,
            args=job_args,
            env=job_env,
            resources=job_resources,
            tags=job_tags,
            collateral_ids=collateral_ids,
        )
        return job, raw_deps

    def _build_param_contexts(
        self, matrix: dict[str, list[Any]], params: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Generate list of variable context dictionaries from matrix or params."""
        if params:
            return params
        if not matrix:
            return [{}]

        keys = list(matrix.keys())
        value_lists = [matrix[k] for k in keys]
        product_combinations = itertools.product(*value_lists)

        return [dict(zip(keys, combo, strict=True)) for combo in product_combinations]

    def _resolve_dependency_references(
        self,
        raw_dependencies: dict[str, list[str]],
        group_job_map: dict[str, list[str]],
        all_job_ids: set[str],
    ) -> dict[str, list[str]]:
        """Resolve dependency references, expanding group IDs into constituent leaf job IDs."""
        resolved: dict[str, list[str]] = {}

        for child_id, parent_refs in raw_dependencies.items():
            parent_job_ids: list[str] = []
            for ref in parent_refs:
                if ref in group_job_map:
                    group_leaves = [
                        j_id for j_id in group_job_map[ref] if j_id != child_id
                    ]
                    parent_job_ids.extend(group_leaves)
                elif ref in all_job_ids:
                    if ref != child_id:
                        parent_job_ids.append(ref)
                else:
                    msg = (
                        f"Dependency reference '{ref}' for job '{child_id}' "
                        f"cannot be resolved (not a recognized job or group ID)"
                    )
                    raise ValueError(msg)

            if parent_job_ids:
                resolved[child_id] = list(dict.fromkeys(parent_job_ids))

        return resolved


__all__ = [
    "GroupExpansionEngine",
    "JobGroupSpec",
    "JobTemplateSpec",
    "ResolvedJobCollection",
    "ResourceOverrideSpec",
]
