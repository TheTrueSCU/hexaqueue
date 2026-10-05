"""Unit tests for Hierarchical Suite and Cascading Matrix Compiler.

Notes/Architectural Intent:
    Comprehensive unit tests verifying deep multi-level suite inheritance,
    Cartesian parameter matrix sweeps, safe template variable interpolation,
    tag/collateral unioning, env/arg cascading, and DAG dependency graph resolution.
"""

import pytest

from hexaqueue_core.domain.exceptions import (
    SuiteCompilationError,
    VariableInterpolationError,
)
from hexaqueue_core.domain.group import ResourceOverrideSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.suite import (
    ContextResolver,
    MatrixExpansionEngine,
    SuiteCompiler,
    SuiteContext,
    SuiteSpec,
    TaskSpec,
    TestSpec,
)


def test_task_spec_validation_and_test_spec_alias() -> None:
    """Verifies TaskSpec invariant validations and TestSpec equivalence."""
    task = TaskSpec(
        id="task_1",
        command="pytest tests/unit",
        args=["-v", "--tb=short"],
        env={"PYTHONDONTWRITEBYTECODE": "1"},
        tags=["fast", "unit"],
    )
    task_id = task.id
    assert task_id == "task_1"
    command = task.command
    assert command == "pytest tests/unit"

    test = TestSpec(
        id="test_1",
        command="pytest tests/integration",
    )
    assert isinstance(test, TaskSpec)
    test_id = test.id
    assert test_id == "test_1"

    with pytest.raises(ValueError, match="Task 'id' cannot be empty"):
        TaskSpec(id="   ", command="echo 1")

    with pytest.raises(ValueError, match="Task 'command' cannot be empty"):
        TaskSpec(id="valid_id", command="   ")


def test_suite_spec_validation_and_tests_alias_merging() -> None:
    """Verifies SuiteSpec validation and automatic reconciliation of tests into tasks."""
    with pytest.raises(ValueError, match="Suite 'id' cannot be empty"):
        SuiteSpec(id="   ")

    test_item = TaskSpec(id="t1", command="run-test")
    suite_with_tests = SuiteSpec(id="suite_tests", tests=[test_item])
    task_count = len(suite_with_tests.tasks)
    assert task_count == 1
    first_task_id = suite_with_tests.tasks[0].id
    assert first_task_id == "t1"

    task_item = TaskSpec(id="t2", command="run-task")
    suite_combined = SuiteSpec(
        id="suite_combined", tasks=[task_item], tests=[test_item]
    )
    combined_count = len(suite_combined.tasks)
    assert combined_count == 2
    task_ids = [t.id for t in suite_combined.tasks]
    assert task_ids == ["t2", "t1"]


def test_matrix_expansion_cartesian_product() -> None:
    """Verifies Cartesian product generation across single and multi-dimensional matrices."""
    empty_expansion = MatrixExpansionEngine.expand_matrix({})
    assert empty_expansion == [{}]

    none_expansion = MatrixExpansionEngine.expand_matrix(None)
    assert none_expansion == [{}]

    single_dim = MatrixExpansionEngine.expand_matrix({"arch": ["x86_64", "arm64"]})
    single_count = len(single_dim)
    assert single_count == 2
    assert single_dim == [{"arch": "x86_64"}, {"arch": "arm64"}]

    multi_dim = MatrixExpansionEngine.expand_matrix(
        {
            "os": ["ubuntu", "debian"],
            "python": ["3.11", "3.12"],
            "opt": ["O2", "O3"],
        }
    )
    multi_count = len(multi_dim)
    assert multi_count == 8

    # Verify every combination is unique
    tuples = [tuple(sorted(d.items())) for d in multi_dim]
    unique_count = len(set(tuples))
    assert unique_count == 8


def test_matrix_variable_interpolation() -> None:
    """Verifies variable interpolation with defaults, escaping, and error handling."""
    ctx = {"arch": "x86_64", "compiler": "clang", "version": "17"}

    # Basic substitution
    s1 = MatrixExpansionEngine.interpolate_string(
        "build --arch=${arch} --compiler=${compiler}", ctx
    )
    assert s1 == "build --arch=x86_64 --compiler=clang"

    # Compatibility with double curly braces
    s2 = MatrixExpansionEngine.interpolate_string("build --arch={{ arch }}", ctx)
    assert s2 == "build --arch=x86_64"

    # Defaults: ${var:-default} and ${var:default}
    s3 = MatrixExpansionEngine.interpolate_string(
        "mode=${mode:-release} debug=${debug:false}", ctx
    )
    assert s3 == "mode=release debug=false"

    # Escaping: $${var} preserves literal ${var}
    s4 = MatrixExpansionEngine.interpolate_string("echo $${arch} is ${arch}", ctx)
    assert s4 == "echo ${arch} is x86_64"

    # Unresolved variable raises VariableInterpolationError
    with pytest.raises(
        VariableInterpolationError, match="Unresolved variable 'missing'"
    ):
        MatrixExpansionEngine.interpolate_string("echo ${missing}", ctx)

    # Allowed unresolved
    s5 = MatrixExpansionEngine.interpolate_string(
        "echo ${missing}", ctx, allow_unresolved=True
    )
    assert s5 == "echo ${missing}"

    # List interpolation
    items = MatrixExpansionEngine.interpolate_list(
        ["--arch=${arch}", "--ver=${version}"], ctx
    )
    assert items == ["--arch=x86_64", "--ver=17"]

    # Dict interpolation
    mapping = MatrixExpansionEngine.interpolate_dict(
        {"KEY_${arch}": "VAL_${version}"}, ctx
    )
    assert mapping == {"KEY_x86_64": "VAL_17"}


def test_cascading_context_inheritance_three_levels() -> None:
    """Verifies 3-level cascading context inheritance (Root -> Parent Suite -> Child Suite -> Task)."""
    root = ContextResolver.create_root_context(
        default_resources=ResourceRequirements(cpus=2, ram_mb=2048),
        global_env={"GLOBAL": "true", "TARGET": "root"},
        global_tags=["global"],
        global_priority=50,
        global_user="ci-bot",
    )

    parent_suite = SuiteSpec(
        id="parent_suite",
        env={"PARENT": "true", "TARGET": "parent"},
        tags=["parent_tag"],
        args=["--parent-arg"],
        resources=ResourceOverrideSpec(cpus=4),
        priority=80,
    )
    parent_ctx = ContextResolver.resolve_suite_context(root, parent_suite)

    assert parent_ctx.env == {
        "GLOBAL": "true",
        "PARENT": "true",
        "TARGET": "parent",
    }
    assert parent_ctx.tags == ["global", "parent_tag"]
    assert parent_ctx.args == ["--parent-arg"]
    assert parent_ctx.resources.cpus == 4
    assert parent_ctx.resources.ram_mb == 2048
    assert parent_ctx.priority == 80
    assert parent_ctx.user == "ci-bot"

    child_suite = SuiteSpec(
        id="child_suite",
        context=SuiteContext(
            env={"CHILD": "true", "TARGET": "child"},
            tags=["child_tag", "global"],
            args=["--child-arg"],
            resources=ResourceOverrideSpec(ram_mb=4096),
        ),
    )
    child_ctx = ContextResolver.resolve_suite_context(parent_ctx, child_suite)

    assert child_ctx.env["TARGET"] == "child"
    assert child_ctx.tags == ["child_tag", "global", "parent_tag"]
    assert child_ctx.args == ["--parent-arg", "--child-arg"]
    assert child_ctx.resources.cpus == 4
    assert child_ctx.resources.ram_mb == 4096

    leaf_task = TaskSpec(
        id="leaf_task",
        command="pytest",
        env={"TASK": "true", "TARGET": "task"},
        tags=["task_tag"],
        args=["--task-arg"],
        resources=ResourceOverrideSpec(gpus=1),
        priority=120,
        checkpointable=True,
    )
    task_ctx = ContextResolver.resolve_task_context(child_ctx, leaf_task)

    assert task_ctx.env["TARGET"] == "task"
    assert task_ctx.env["GLOBAL"] == "true"
    assert task_ctx.env["PARENT"] == "true"
    assert task_ctx.env["CHILD"] == "true"
    assert task_ctx.env["TASK"] == "true"
    assert task_ctx.tags == ["child_tag", "global", "parent_tag", "task_tag"]
    assert task_ctx.args == ["--parent-arg", "--child-arg", "--task-arg"]
    assert task_ctx.resources.cpus == 4
    assert task_ctx.resources.ram_mb == 4096
    assert task_ctx.resources.gpus == 1
    assert task_ctx.priority == 120
    assert task_ctx.checkpointable is True


def test_suite_compiler_hierarchical_matrix_expansion() -> None:
    """Verifies compilation of hierarchical suites with nested matrices and variable interpolation."""
    suite = SuiteSpec(
        id="root",
        env={"BASE_PATH": "/workspace"},
        matrix={"os": ["ubuntu", "rhel"]},
        suites=[
            SuiteSpec(
                id="ml_subsystem",
                matrix={"backend": ["cuda", "rocm"]},
                tasks=[
                    TaskSpec(
                        id="train",
                        name="train_${os}_${backend}_b${batch}",
                        command="python train.py --os ${os} --backend ${backend} --batch ${batch}",
                        matrix={"batch": [16, 32]},
                        tags=["ml", "${backend}"],
                    ),
                    TaskSpec(
                        id="eval",
                        command="python eval.py --backend ${backend}",
                        depends_on=["train"],
                    ),
                ],
            )
        ],
    )

    compiler = SuiteCompiler()
    result = compiler.compile(suite=suite, run_id="run-matrix-1")

    # Suite matrix (2 os) * ML matrix (2 backends) = 4 combinations
    # Each combination has:
    #   - 1 train task with matrix (2 batch) = 2 train jobs
    #   - 1 eval task with no matrix = 1 eval job
    # Total per combo = 3 jobs. Total jobs = 4 * 3 = 12 jobs!
    job_count = result.job_count
    assert job_count == 12

    # Check that each train job has correct interpolated command
    train_job = result.get_job("train[backend=cuda,batch=16,os=ubuntu]")
    assert train_job is not None
    cmd = train_job.command
    assert "train.py" in cmd
    assert "--batch 16" in cmd

    # Verify all jobs can be topologically sorted
    topological_order = result.topological_order()
    order_len = len(topological_order)
    assert order_len == 12

    # Verify eval jobs depend on train jobs
    eval_job_ids = [j.id for j in result.jobs if j.id.startswith("eval")]
    train_job_ids = [j.id for j in result.jobs if j.id.startswith("train")]
    for e_id in eval_job_ids:
        deps = result.dependencies.get(e_id, [])
        dep_parents = [d.parent_job_id for d in deps]
        for t_id in train_job_ids:
            assert t_id in dep_parents


def test_suite_compiler_detects_cyclic_dependency() -> None:
    """Verifies that SuiteCompiler detects cyclic dependencies and raises SuiteCompilationError."""
    suite = SuiteSpec(
        id="cycle_suite",
        tasks=[
            TaskSpec(id="task_a", command="echo a", depends_on=["task_b"]),
            TaskSpec(id="task_b", command="echo b", depends_on=["task_a"]),
        ],
    )

    compiler = SuiteCompiler()
    with pytest.raises(SuiteCompilationError, match="Cyclic dependency detected"):
        compiler.compile(suite=suite, run_id="run-cycle")


def test_suite_compiler_detects_duplicate_job_ids() -> None:
    """Verifies that SuiteCompiler detects duplicate job IDs and raises SuiteCompilationError."""
    suite = SuiteSpec(
        id="dup_suite",
        tasks=[
            TaskSpec(id="task_dup", command="echo 1"),
            TaskSpec(id="task_dup", command="echo 2"),
        ],
    )

    compiler = SuiteCompiler()
    with pytest.raises(SuiteCompilationError, match="Duplicate job ID 'task_dup'"):
        compiler.compile(suite=suite, run_id="run-dup")


def test_suite_compiler_detects_unresolved_dependency() -> None:
    """Verifies that SuiteCompiler detects unresolvable dependency references."""
    suite = SuiteSpec(
        id="bad_dep_suite",
        tasks=[
            TaskSpec(id="task_1", command="echo 1", depends_on=["ghost_task"]),
        ],
    )

    compiler = SuiteCompiler()
    with pytest.raises(
        SuiteCompilationError,
        match="Dependency reference 'ghost_task' for job 'task_1' cannot be resolved",
    ):
        compiler.compile(suite=suite, run_id="run-bad-dep")


def test_suite_to_suite_dependency_resolution() -> None:
    """Verifies suite-level dependency linking where child suite jobs depend on parent suite jobs."""
    setup_suite = SuiteSpec(
        id="setup_suite",
        tasks=[
            TaskSpec(id="db_migrate", command="alembic upgrade head"),
            TaskSpec(
                id="seed_data", command="python seed.py", depends_on=["db_migrate"]
            ),
        ],
    )
    test_suite = SuiteSpec(
        id="test_suite",
        depends_on=["setup_suite"],
        tasks=[
            TaskSpec(id="run_tests", command="pytest tests/"),
        ],
    )
    root = SuiteSpec(id="pipeline", suites=[setup_suite, test_suite])

    compiler = SuiteCompiler()
    result = compiler.compile(suite=root, run_id="run-pipeline")

    count = result.job_count
    assert count == 3

    test_deps = result.dependencies.get("run_tests", [])
    parent_ids = [d.parent_job_id for d in test_deps]
    assert "db_migrate" in parent_ids
    assert "seed_data" in parent_ids

    # Topological execution order must execute setup jobs before test job
    order = result.topological_order()
    assert order.index("db_migrate") < order.index("seed_data")
    assert order.index("seed_data") < order.index("run_tests")
