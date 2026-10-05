"""Hierarchical workload bundles, cascading parameter inheritance, and matrix compiler.

Notes/Architectural Intent:
    Provides recursive suite tree models (SuiteSpec, TaskSpec/TestSpec), cascading
    context inheritance (ContextResolver), Cartesian product matrix expansion and
    safe template variable interpolation (MatrixExpansionEngine), compiling
    hierarchical workloads deterministically into flattened JobSpec batches
    and acyclic DAG dependency graphs.
"""

import itertools
import re
from collections.abc import Mapping, Sequence
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hexaqueue_core.domain.dag import DependencySpec, JobDagEngine, TriggerCondition
from hexaqueue_core.domain.exceptions import (
    SuiteCompilationError,
    VariableInterpolationError,
)
from hexaqueue_core.domain.group import ResourceOverrideSpec
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.notification import NotificationPolicy
from hexaqueue_core.domain.resources import ResourceRequirements

_VAR_PATTERN = re.compile(
    r"(?<!\$)\$\{\s*([a-zA-Z0-9_\.\-]+)\s*(?::\-?([^}]*))?\}|\{\{\s*([a-zA-Z0-9_\.\-]+)\s*\}\}"
)


def _merge_resource_overrides(
    base: ResourceRequirements,
    override: ResourceRequirements | ResourceOverrideSpec | None,
) -> ResourceRequirements:
    """Merge resource requirements or overrides on top of a base ResourceRequirements.

    Args:
        base: Base resource requirements to inherit from.
        override: Specific ResourceRequirements or ResourceOverrideSpec, or None.

    Returns:
        Merged ResourceRequirements instance.
    """
    if override is None:
        return base
    if isinstance(override, ResourceOverrideSpec):
        return override.apply_to(base)
    return override


class TaskSpec(BaseModel):
    """Specification of a concrete leaf task or test in a hierarchical suite.

    Args:
        id: Unique task identifier or parameterized template (e.g. 'test_inference_${batch_size}').
        name: Optional human-readable task name template.
        command: Executable command string or template (e.g. 'pytest tests/ -k ${filter}').
        args: List of command-line arguments or templates.
        env: Dictionary of task-specific environment variables.
        resources: Compute and hardware requirements or overrides.
        tags: Affinity, placement, and categorization tags.
        collateral_ids: Associated collateral bundle IDs required by this task.
        matrix: Cartesian product matrix mapping variable name to sequence of values.
        variables: Key-value dictionary of local parameters for interpolation.
        depends_on: List of upstream task or suite IDs this task depends on.
        priority: Base priority level override.
        user: User identifier override.
        checkpointable: Whether task can be safely checkpointed upon preemption.
        notifications: Notification policies for lifecycle events.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    __test__ = False

    id: str = Field(description="Unique task identifier template")
    name: str | None = Field(
        default=None, description="Human-readable task name template"
    )
    command: str = Field(description="Executable command string or template")
    args: list[str] = Field(default_factory=list, description="Command-line arguments")
    env: dict[str, str] = Field(
        default_factory=dict, description="Task-specific environment variables"
    )
    resources: ResourceRequirements | ResourceOverrideSpec | None = Field(
        default=None, description="Resource requirements or partial overrides"
    )
    tags: list[str] = Field(default_factory=list, description="Task tags")
    collateral_ids: list[str] = Field(
        default_factory=list, description="Associated collateral bundle IDs"
    )
    matrix: dict[str, list[Any]] = Field(
        default_factory=dict,
        description="Combinatorial parameter matrix sweep for this task",
    )
    variables: dict[str, Any] = Field(
        default_factory=dict, description="Template variables for interpolation"
    )
    depends_on: list[str] = Field(
        default_factory=list, description="Upstream prerequisite task or suite IDs"
    )
    priority: int | None = Field(
        default=None, description="Optional priority level override"
    )
    user: str | None = Field(
        default=None, description="Optional user identifier override"
    )
    checkpointable: bool | None = Field(
        default=None, description="Optional checkpointable override"
    )
    notifications: list[NotificationPolicy] = Field(
        default_factory=list, description="Lifecycle event notification policies"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate task invariants."""
        if not self.id.strip():
            msg = "Task 'id' cannot be empty"
            raise ValueError(msg)
        if not self.command.strip():
            msg = "Task 'command' cannot be empty"
            raise ValueError(msg)
        return self


# TestSpec is an alias for TaskSpec to provide seamless test suite terminology.
TestSpec = TaskSpec


class SuiteContext(BaseModel):
    """Cascading context specification inherited by descendant child suites and leaf tasks.

    Args:
        env: Inherited environment variables.
        resources: Inherited resource requirements or overrides.
        args: Inherited command-line arguments (prepended to child arguments).
        tags: Inherited metadata and placement tags.
        collateral_ids: Inherited collateral bundle IDs.
        variables: Inherited template variables for interpolation.
        priority: Inherited base priority.
        user: Inherited user or team account identifier.
        checkpointable: Inherited checkpointable flag.
        depends_on: Inherited dependencies applied to all constituent tasks.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    env: dict[str, str] = Field(
        default_factory=dict, description="Inherited environment variables"
    )
    resources: ResourceRequirements | ResourceOverrideSpec | None = Field(
        default=None, description="Inherited resource defaults"
    )
    args: list[str] = Field(
        default_factory=list, description="Inherited command-line flags/arguments"
    )
    tags: list[str] = Field(default_factory=list, description="Inherited tags")
    collateral_ids: list[str] = Field(
        default_factory=list, description="Inherited collateral bundle IDs"
    )
    variables: dict[str, Any] = Field(
        default_factory=dict, description="Inherited template variables"
    )
    priority: int | None = Field(
        default=None, description="Inherited base priority level"
    )
    user: str | None = Field(default=None, description="Inherited user identifier")
    checkpointable: bool | None = Field(
        default=None, description="Inherited checkpointable capability"
    )
    depends_on: list[str] = Field(
        default_factory=list, description="Inherited dependencies"
    )


class SuiteSpec(BaseModel):
    """Hierarchical workload bundle containing nested child suites and leaf tasks.

    Args:
        id: Unique suite identifier.
        name: Optional human-readable suite title.
        context: Optional explicit SuiteContext bundle.
        env: Direct environment variables (merged with context).
        resources: Direct resource defaults (merged with context).
        args: Direct command-line arguments (merged with context).
        tags: Direct categorization tags (merged with context).
        collateral_ids: Direct collateral dependencies (merged with context).
        variables: Direct template variables (merged with context).
        priority: Direct priority setting.
        user: Direct user setting.
        checkpointable: Direct checkpointable setting.
        matrix: Cartesian product parameter sweep for this suite branch.
        suites: Sequence of nested child SuiteSpec instances.
        tasks: Sequence of leaf TaskSpec instances.
        tests: Optional alias for tasks; merged with tasks.
        depends_on: Upstream suite or task dependencies required before this suite executes.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Unique suite identifier")
    name: str | None = Field(default=None, description="Human-readable suite title")
    context: SuiteContext | None = Field(
        default=None, description="Cascading suite context"
    )
    env: dict[str, str] = Field(
        default_factory=dict, description="Suite-scoped environment variables"
    )
    resources: ResourceRequirements | ResourceOverrideSpec | None = Field(
        default=None, description="Suite-scoped resource defaults"
    )
    args: list[str] = Field(
        default_factory=list, description="Suite-scoped command arguments"
    )
    tags: list[str] = Field(default_factory=list, description="Suite-scoped tags")
    collateral_ids: list[str] = Field(
        default_factory=list, description="Suite-scoped collateral bundle IDs"
    )
    variables: dict[str, Any] = Field(
        default_factory=dict, description="Suite-scoped template variables"
    )
    priority: int | None = Field(
        default=None, description="Suite-scoped priority default"
    )
    user: str | None = Field(default=None, description="Suite-scoped user default")
    checkpointable: bool | None = Field(
        default=None, description="Suite-scoped checkpointable default"
    )
    matrix: dict[str, list[Any]] = Field(
        default_factory=dict,
        description="Combinatorial parameter matrix sweep for this suite branch",
    )
    suites: list["SuiteSpec"] = Field(
        default_factory=list, description="Nested child suites"
    )
    tasks: list[TaskSpec] = Field(
        default_factory=list, description="Leaf task specifications"
    )
    tests: list[TaskSpec] = Field(
        default_factory=list, description="Alias/synonym for leaf task specifications"
    )
    depends_on: list[str] = Field(
        default_factory=list, description="Dependencies required for entire suite"
    )

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        """Validate suite invariants and reconcile tasks with tests."""
        if not self.id.strip():
            msg = "Suite 'id' cannot be empty"
            raise ValueError(msg)
        if self.tests and not self.tasks:
            object.__setattr__(self, "tasks", list(self.tests))
        elif self.tests and self.tasks:
            object.__setattr__(self, "tasks", list(self.tasks) + list(self.tests))
        return self


class ResolvedContext(BaseModel):
    """Immutable resolved snapshot of inherited parameters at a specific tree node.

    Args:
        env: Merged environment variables.
        resources: Fully resolved compute resource requirements.
        args: Prepended/merged command arguments.
        tags: Deduplicated union of affinity tags.
        collateral_ids: Deduplicated union of collateral bundle IDs.
        variables: Merged template variables.
        priority: Effective job priority.
        user: Effective user identifier.
        checkpointable: Effective checkpointable flag.
        depends_on: List of upstream prerequisite IDs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    env: dict[str, str] = Field(default_factory=dict)
    resources: ResourceRequirements = Field(default_factory=ResourceRequirements)
    args: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    collateral_ids: list[str] = Field(default_factory=list)
    variables: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=100)
    user: str = Field(default="default")
    checkpointable: bool = Field(default=False)
    depends_on: list[str] = Field(default_factory=list)


class MatrixExpansionEngine:
    """Engine for Cartesian parameter matrix expansion and template variable interpolation.

    Notes/Architectural Intent:
        Guarantees deterministic combinatorial expansion order (sorted matrix keys)
        and enforces zero unmapped template variable leaks via VariableInterpolationError.
    """

    @classmethod
    def expand_matrix(
        cls, matrix: Mapping[str, Sequence[Any]] | None
    ) -> list[dict[str, Any]]:
        """Generate Cartesian product parameter combinations from a matrix dictionary.

        Args:
            matrix: Mapping from variable name to sequence of discrete values.

        Returns:
            List of concrete parameter context dictionaries. Returns [{}] if matrix is empty.
        """
        if not matrix:
            return [{}]

        sorted_keys = sorted(matrix.keys())
        value_lists = [matrix[k] for k in sorted_keys]
        product_combinations = itertools.product(*value_lists)

        return [
            dict(zip(sorted_keys, combo, strict=True)) for combo in product_combinations
        ]

    @classmethod
    def interpolate_string(
        cls,
        template_str: str,
        context: dict[str, Any],
        allow_unresolved: bool = False,
    ) -> str:
        """Interpolate variable placeholders (${var}, ${var:-default}, {{ var }}) in a string.

        Supports variable escaping via double dollar signs ($${var} -> ${var}).

        Args:
            template_str: Input template string containing placeholders.
            context: Mapping of variable names to values.
            allow_unresolved: If False, raises VariableInterpolationError on missing variables.

        Returns:
            Fully interpolated string.

        Raises:
            VariableInterpolationError: If an unmapped variable without default is encountered.
        """
        if "${" not in template_str and "{{" not in template_str:
            return template_str.replace("$$", "$")

        def _repl(match: re.Match[str]) -> str:
            if match.group(1) is not None:
                key = match.group(1).strip()
                default = match.group(2)
            else:
                key = match.group(3).strip()
                default = None

            if key in context:
                return str(context[key])
            if default is not None:
                return default
            if allow_unresolved:
                return match.group(0)

            msg = f"Unresolved variable '{key}' in template: {template_str}"
            raise VariableInterpolationError(msg)

        substituted = _VAR_PATTERN.sub(_repl, template_str)
        return substituted.replace("$$", "$")

    @classmethod
    def interpolate_list(
        cls,
        items: Sequence[str],
        context: dict[str, Any],
        allow_unresolved: bool = False,
    ) -> list[str]:
        """Interpolate a list of template strings.

        Args:
            items: Sequence of template strings.
            context: Variable context dictionary.
            allow_unresolved: Whether to allow unmapped variables.

        Returns:
            List of interpolated strings.
        """
        return [
            cls.interpolate_string(item, context, allow_unresolved=allow_unresolved)
            for item in items
        ]

    @classmethod
    def interpolate_dict(
        cls,
        mapping: dict[str, str],
        context: dict[str, Any],
        allow_unresolved: bool = False,
    ) -> dict[str, str]:
        """Interpolate keys and values of a string dictionary.

        Args:
            mapping: Key-value dictionary with template values.
            context: Variable context dictionary.
            allow_unresolved: Whether to allow unmapped variables.

        Returns:
            Dictionary with interpolated keys and values.
        """
        result: dict[str, str] = {}
        for k, v in mapping.items():
            interp_k = cls.interpolate_string(
                k, context, allow_unresolved=allow_unresolved
            )
            interp_v = cls.interpolate_string(
                v, context, allow_unresolved=allow_unresolved
            )
            result[interp_k] = interp_v
        return result


class ContextResolver:
    """Pure cascading context inheritance resolver.

    Notes/Architectural Intent:
        Implements deterministic cascading inheritance semantics:
        - Child scalar overrides parent scalar (priority, user, checkpointable).
        - Dictionary keys merged with child taking precedence (env, variables).
        - Tags and collateral IDs are unified (deduplicated sorted set).
        - Arguments are appended (parent args prepended to child args).
        - Resource overrides applied on top of inherited parent requirements.
        - Dependencies are concatenated preserving declaration order.
    """

    @classmethod
    def create_root_context(
        cls,
        default_resources: ResourceRequirements | None = None,
        global_env: dict[str, str] | None = None,
        global_tags: list[str] | None = None,
        global_resources: ResourceRequirements | ResourceOverrideSpec | None = None,
        global_variables: dict[str, Any] | None = None,
        global_priority: int = 100,
        global_user: str = "default",
    ) -> ResolvedContext:
        """Create the root resolved context for a suite compilation run.

        Args:
            default_resources: Base resource requirements.
            global_env: Optional global environment variables.
            global_tags: Optional global tags.
            global_resources: Optional global resource defaults or overrides.
            global_variables: Optional global template variables.
            global_priority: Default priority level.
            global_user: Default user identifier.

        Returns:
            ResolvedContext root instance.
        """
        base_res = default_resources or ResourceRequirements()
        effective_res = _merge_resource_overrides(base_res, global_resources)

        return ResolvedContext(
            env=dict(global_env or {}),
            resources=effective_res,
            args=[],
            tags=sorted(set(global_tags or [])),
            collateral_ids=[],
            variables=dict(global_variables or {}),
            priority=global_priority,
            user=global_user,
            checkpointable=False,
            depends_on=[],
        )

    @classmethod
    def resolve_suite_context(
        cls, parent: ResolvedContext, suite: SuiteSpec
    ) -> ResolvedContext:
        """Resolve cascading context for a child SuiteSpec node.

        Args:
            parent: Resolved context inherited from parent tree scope.
            suite: Current SuiteSpec node.

        Returns:
            A new ResolvedContext reflecting suite-level overrides.
        """
        ctx = suite.context or SuiteContext()

        merged_env = {**parent.env, **ctx.env, **suite.env}
        merged_vars = {**parent.variables, **ctx.variables, **suite.variables}
        merged_args = parent.args + ctx.args + suite.args
        merged_tags = sorted(set(parent.tags) | set(ctx.tags) | set(suite.tags))
        merged_collateral = sorted(
            set(parent.collateral_ids)
            | set(ctx.collateral_ids)
            | set(suite.collateral_ids)
        )

        res_step = _merge_resource_overrides(parent.resources, ctx.resources)
        final_res = _merge_resource_overrides(res_step, suite.resources)

        priority = suite.priority or ctx.priority or parent.priority
        user = suite.user or ctx.user or parent.user
        checkpointable = (
            suite.checkpointable
            if suite.checkpointable is not None
            else (
                ctx.checkpointable
                if ctx.checkpointable is not None
                else parent.checkpointable
            )
        )

        inherited_deps = list(
            dict.fromkeys(parent.depends_on + ctx.depends_on + suite.depends_on)
        )

        return ResolvedContext(
            env=merged_env,
            resources=final_res,
            args=merged_args,
            tags=merged_tags,
            collateral_ids=merged_collateral,
            variables=merged_vars,
            priority=priority,
            user=user,
            checkpointable=checkpointable,
            depends_on=inherited_deps,
        )

    @classmethod
    def resolve_task_context(
        cls, parent: ResolvedContext, task: TaskSpec
    ) -> ResolvedContext:
        """Resolve cascading context for a leaf TaskSpec execution unit.

        Args:
            parent: Resolved context inherited from parent suite scope.
            task: Current leaf TaskSpec.

        Returns:
            A new ResolvedContext reflecting task-level overrides.
        """
        merged_env = {**parent.env, **task.env}
        merged_vars = {**parent.variables, **task.variables}
        merged_args = parent.args + task.args
        merged_tags = sorted(set(parent.tags) | set(task.tags))
        merged_collateral = sorted(
            set(parent.collateral_ids) | set(task.collateral_ids)
        )

        final_res = _merge_resource_overrides(parent.resources, task.resources)

        priority = task.priority if task.priority is not None else parent.priority
        user = task.user if task.user is not None else parent.user
        checkpointable = (
            task.checkpointable
            if task.checkpointable is not None
            else parent.checkpointable
        )

        effective_deps = list(dict.fromkeys(parent.depends_on + task.depends_on))

        return ResolvedContext(
            env=merged_env,
            resources=final_res,
            args=merged_args,
            tags=merged_tags,
            collateral_ids=merged_collateral,
            variables=merged_vars,
            priority=priority,
            user=user,
            checkpointable=checkpointable,
            depends_on=effective_deps,
        )


class SuiteCompilationResult(BaseModel):
    """Compilation output comprising flattened JobSpecs and resolved DAG dependencies.

    Args:
        jobs: List of flattened, concrete JobSpec entities ready for dispatch.
        dependencies: Adjacency map of child job ID -> list of DependencySpec prerequisites.
        suite_task_map: Mapping from suite ID -> list of constituent leaf job IDs.
        dag: Validated JobDagEngine instance representing execution dependencies.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    jobs: list[JobSpec] = Field(description="Flattened list of concrete jobs")
    dependencies: dict[str, list[DependencySpec]] = Field(
        default_factory=dict, description="Job-to-job dependency mappings"
    )
    suite_task_map: dict[str, list[str]] = Field(
        default_factory=dict, description="Mapping of suite ID to leaf job IDs"
    )
    dag: JobDagEngine = Field(description="Topologically validated DAG engine")

    @property
    def job_count(self) -> int:
        """Total number of compiled leaf jobs."""
        return len(self.jobs)

    def get_job(self, job_id: str) -> JobSpec | None:
        """Retrieve a compiled job by its unique identifier.

        Args:
            job_id: Unique job identifier.

        Returns:
            Matching JobSpec, or None if not found.
        """
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def topological_order(self) -> list[str]:
        """Compute the deterministic topological execution order of compiled jobs.

        Returns:
            List of job IDs ordered from prerequisites to dependents.
        """
        all_ids = {j.id for j in self.jobs}
        return self.dag.validate_and_topological_sort(all_ids)


class SuiteCompiler:
    """Compiler that flattens hierarchical SuiteSpec trees into executable DAGs.

    Notes/Architectural Intent:
        Coordinates multi-level cascading parameter inheritance, multi-dimensional
        Cartesian matrix sweeps, safe template interpolation, and dependency
        resolution into fully validated JobSpec batches.
    """

    def __init__(self, default_resources: ResourceRequirements | None = None) -> None:
        """Initialize compiler with optional default compute requirements.

        Args:
            default_resources: Base resource requirements for jobs.
        """
        self._default_resources = default_resources or ResourceRequirements()

    def compile(
        self,
        suite: SuiteSpec,
        run_id: str,
        global_env: dict[str, str] | None = None,
        global_tags: list[str] | None = None,
        global_resources: ResourceRequirements | ResourceOverrideSpec | None = None,
        global_variables: dict[str, Any] | None = None,
    ) -> SuiteCompilationResult:
        """Compile a SuiteSpec tree into a concrete SuiteCompilationResult.

        Args:
            suite: Root hierarchical suite specification.
            run_id: Root run identifier to associate with generated jobs.
            global_env: Optional global environment variables.
            global_tags: Optional global placement tags.
            global_resources: Optional global resource defaults.
            global_variables: Optional global template variables.

        Returns:
            Fully resolved SuiteCompilationResult.

        Raises:
            SuiteCompilationError: If duplicate job IDs or dependency cycles exist.
            VariableInterpolationError: If template variables cannot be resolved.
        """
        root_context = ContextResolver.create_root_context(
            default_resources=self._default_resources,
            global_env=global_env,
            global_tags=global_tags,
            global_resources=global_resources,
            global_variables=global_variables,
        )

        accumulated_jobs: list[JobSpec] = []
        raw_dependencies: dict[str, list[str]] = {}
        suite_task_map: dict[str, list[str]] = {}
        task_job_map: dict[str, list[str]] = {}

        self._compile_suite_recursive(
            suite=suite,
            parent_context=root_context,
            run_id=run_id,
            accumulated_jobs=accumulated_jobs,
            raw_dependencies=raw_dependencies,
            suite_task_map=suite_task_map,
            task_job_map=task_job_map,
        )

        self._verify_unique_job_ids(accumulated_jobs)

        resolved_deps = self._resolve_dependency_graph(
            raw_dependencies=raw_dependencies,
            suite_task_map=suite_task_map,
            task_job_map=task_job_map,
            all_job_ids={j.id for j in accumulated_jobs},
        )

        dag = JobDagEngine(resolved_deps)
        all_ids = {j.id for j in accumulated_jobs}
        try:
            dag.validate_and_topological_sort(all_ids)
        except Exception as exc:
            msg = f"Suite compilation failed DAG dependency validation: {exc}"
            raise SuiteCompilationError(msg) from exc

        return SuiteCompilationResult(
            jobs=accumulated_jobs,
            dependencies=resolved_deps,
            suite_task_map=suite_task_map,
            dag=dag,
        )

    def _compile_suite_recursive(
        self,
        suite: SuiteSpec,
        parent_context: ResolvedContext,
        run_id: str,
        accumulated_jobs: list[JobSpec],
        raw_dependencies: dict[str, list[str]],
        suite_task_map: dict[str, list[str]],
        task_job_map: dict[str, list[str]],
        parent_matrix_params: dict[str, Any] | None = None,
    ) -> list[str]:
        """Recursively compile a suite node across its matrix combinations."""
        resolved_context = ContextResolver.resolve_suite_context(parent_context, suite)
        suite_param_contexts = MatrixExpansionEngine.expand_matrix(suite.matrix)
        created_suite_job_ids: list[str] = []
        base_params = dict(parent_matrix_params or {})

        for s_ctx in suite_param_contexts:
            combined_matrix_params = {**base_params, **s_ctx}
            combined_vars = {**resolved_context.variables, **combined_matrix_params}
            interpolated_env = MatrixExpansionEngine.interpolate_dict(
                resolved_context.env, combined_vars
            )
            step_context = resolved_context.model_copy(
                update={"variables": combined_vars, "env": interpolated_env}
            )

            for task_spec in suite.tasks:
                task_job_ids = self._compile_task(
                    task=task_spec,
                    parent_context=step_context,
                    run_id=run_id,
                    accumulated_jobs=accumulated_jobs,
                    raw_dependencies=raw_dependencies,
                    task_job_map=task_job_map,
                    suite_matrix_params=combined_matrix_params,
                )
                created_suite_job_ids.extend(task_job_ids)

            for child_suite in suite.suites:
                child_job_ids = self._compile_suite_recursive(
                    suite=child_suite,
                    parent_context=step_context,
                    run_id=run_id,
                    accumulated_jobs=accumulated_jobs,
                    raw_dependencies=raw_dependencies,
                    suite_task_map=suite_task_map,
                    task_job_map=task_job_map,
                    parent_matrix_params=combined_matrix_params,
                )
                created_suite_job_ids.extend(child_job_ids)

        suite_task_map.setdefault(suite.id, []).extend(created_suite_job_ids)
        return created_suite_job_ids

    def _compile_task(
        self,
        task: TaskSpec,
        parent_context: ResolvedContext,
        run_id: str,
        accumulated_jobs: list[JobSpec],
        raw_dependencies: dict[str, list[str]],
        task_job_map: dict[str, list[str]],
        suite_matrix_params: dict[str, Any] | None = None,
    ) -> list[str]:
        """Compile a leaf task across its matrix combinations into concrete JobSpecs."""
        resolved_context = ContextResolver.resolve_task_context(parent_context, task)
        task_param_contexts = MatrixExpansionEngine.expand_matrix(task.matrix)
        created_task_job_ids: list[str] = []
        base_suite_params = dict(suite_matrix_params or {})

        for t_ctx in task_param_contexts:
            combined_matrix_params = {**base_suite_params, **t_ctx}
            scoped_vars = {**resolved_context.variables, **combined_matrix_params}
            full_context = {**resolved_context.env, **scoped_vars}

            job_id = self._build_deterministic_job_id(
                task.id, full_context, combined_matrix_params
            )
            job_name = (
                MatrixExpansionEngine.interpolate_string(task.name, full_context)
                if task.name
                else job_id
            )

            job_env = MatrixExpansionEngine.interpolate_dict(
                resolved_context.env, full_context
            )
            job_command = MatrixExpansionEngine.interpolate_string(
                task.command, {**full_context, **job_env}
            )
            job_args = MatrixExpansionEngine.interpolate_list(
                resolved_context.args, {**full_context, **job_env}
            )
            job_collateral = MatrixExpansionEngine.interpolate_list(
                resolved_context.collateral_ids, full_context
            )
            job_tags = MatrixExpansionEngine.interpolate_list(
                resolved_context.tags, full_context
            )

            job_spec = JobSpec(
                id=job_id,
                run_id=run_id,
                name=job_name,
                command=job_command,
                args=job_args,
                env=job_env,
                resources=resolved_context.resources,
                collateral_ids=job_collateral,
                tags=job_tags,
                notifications=task.notifications,
                user=resolved_context.user,
                priority=resolved_context.priority,
                checkpointable=resolved_context.checkpointable,
            )

            accumulated_jobs.append(job_spec)
            created_task_job_ids.append(job_id)

            if resolved_context.depends_on:
                interp_deps = MatrixExpansionEngine.interpolate_list(
                    resolved_context.depends_on, full_context
                )
                raw_dependencies[job_id] = interp_deps

        task_job_map.setdefault(task.id, []).extend(created_task_job_ids)
        return created_task_job_ids

    def _build_deterministic_job_id(
        self,
        task_id_template: str,
        context: dict[str, Any],
        matrix_params: dict[str, Any],
    ) -> str:
        """Construct deterministic job ID with matrix parameter suffix if needed."""
        interpolated_id = MatrixExpansionEngine.interpolate_string(
            task_id_template, context
        )
        if not matrix_params:
            return interpolated_id

        unrepresented_keys = [
            k for k in sorted(matrix_params.keys()) if f"${{{k}" not in task_id_template
        ]
        if not unrepresented_keys:
            return interpolated_id

        param_tokens = [f"{k}={matrix_params[k]}" for k in unrepresented_keys]
        param_suffix = f"[{','.join(param_tokens)}]"
        return f"{interpolated_id}{param_suffix}"

    def _verify_unique_job_ids(self, jobs: list[JobSpec]) -> None:
        """Validate that no duplicate job IDs exist."""
        seen: set[str] = set()
        for job in jobs:
            if job.id in seen:
                msg = f"Duplicate job ID '{job.id}' generated during suite compilation"
                raise SuiteCompilationError(msg)
            seen.add(job.id)

    def _resolve_dependency_graph(
        self,
        raw_dependencies: dict[str, list[str]],
        suite_task_map: dict[str, list[str]],
        task_job_map: dict[str, list[str]],
        all_job_ids: set[str],
    ) -> dict[str, list[DependencySpec]]:
        """Resolve symbolic suite or task references into concrete JobSpec dependencies."""
        resolved: dict[str, list[DependencySpec]] = {}

        for child_id, parent_refs in raw_dependencies.items():
            parent_job_ids: list[str] = []
            for ref in parent_refs:
                parent_job_ids.extend(
                    self._resolve_single_dependency_ref(
                        ref=ref,
                        child_id=child_id,
                        suite_task_map=suite_task_map,
                        task_job_map=task_job_map,
                        all_job_ids=all_job_ids,
                    )
                )

            unique_parents = list(dict.fromkeys(parent_job_ids))
            if unique_parents:
                resolved[child_id] = [
                    DependencySpec(
                        parent_job_id=p_id, condition=TriggerCondition.AFTER_OK
                    )
                    for p_id in unique_parents
                ]

        return resolved

    def _resolve_single_dependency_ref(
        self,
        ref: str,
        child_id: str,
        suite_task_map: dict[str, list[str]],
        task_job_map: dict[str, list[str]],
        all_job_ids: set[str],
    ) -> list[str]:
        """Resolve a single symbolic dependency reference into concrete job IDs."""
        if ref in suite_task_map:
            return [j for j in suite_task_map[ref] if j != child_id]
        if ref in task_job_map:
            return [j for j in task_job_map[ref] if j != child_id]
        if ref in all_job_ids:
            return [ref] if ref != child_id else []

        msg = (
            f"Dependency reference '{ref}' for job '{child_id}' "
            f"cannot be resolved (not a recognized suite, task, or job ID)"
        )
        raise SuiteCompilationError(msg)


__all__ = [
    "ContextResolver",
    "MatrixExpansionEngine",
    "ResolvedContext",
    "SuiteCompilationResult",
    "SuiteCompiler",
    "SuiteContext",
    "SuiteSpec",
    "TaskSpec",
    "TestSpec",
]
