"""Property-based invariant and fuzz testing for Hierarchical Suite and Matrix Expansion.

Notes/Architectural Intent:
    Verifies that the SuiteCompiler and MatrixExpansionEngine strictly uphold invariants:
    1. Deterministic resolution: Identical inputs produce identical job specs and DAG topology.
    2. Absence of variable leaks: All templates resolve completely or raise VariableInterpolationError.
    3. Combinatorial cardinality: Matrix expansion yields exactly product of dimension lengths.
"""

import math

from hypothesis import given
from hypothesis import strategies as st

from hexaqueue_core.domain.exceptions import VariableInterpolationError
from hexaqueue_core.domain.suite import (
    MatrixExpansionEngine,
    SuiteCompiler,
    SuiteSpec,
    TaskSpec,
)

# Strategy for variable names (alphanumeric identifiers)
var_name_st = st.from_regex(r"[a-z][a-z0-9_]{1,8}", fullmatch=True)

# Strategy for variable values (simple strings or ints)
var_value_st = st.one_of(
    st.from_regex(r"[a-zA-Z0-9_\-]{1,10}", fullmatch=True),
    st.integers(min_value=-1000, max_value=1000).map(str),
)


@st.composite
def matrix_dict_strategy(draw: st.DrawFn) -> dict[str, list[str]]:
    """Generate valid parameter matrices with bounded dimensions."""
    num_vars = draw(st.integers(min_value=0, max_value=4))
    if num_vars == 0:
        return {}
    keys = draw(
        st.lists(var_name_st, min_size=num_vars, max_size=num_vars, unique=True)
    )
    matrix: dict[str, list[str]] = {}
    for key in keys:
        values = draw(st.lists(var_value_st, min_size=1, max_size=3, unique=True))
        matrix[key] = values
    return matrix


@given(matrix_dict_strategy())
def test_matrix_expansion_cardinality_and_uniqueness(
    matrix: dict[str, list[str]],
) -> None:
    """Verifies that MatrixExpansionEngine produces exactly prod(|v|) unique combinations."""
    expanded = MatrixExpansionEngine.expand_matrix(matrix)

    expected_len = 1 if not matrix else math.prod(len(v) for v in matrix.values())

    actual_len = len(expanded)
    assert actual_len == expected_len

    # Assert uniqueness of all combinations
    tuples = [tuple(sorted(combo.items())) for combo in expanded]
    unique_count = len(set(tuples))
    assert unique_count == expected_len


@given(
    st.dictionaries(var_name_st, var_value_st, min_size=1, max_size=5),
    st.lists(var_name_st, min_size=1, max_size=3),
)
def test_variable_interpolation_no_leak(
    context: dict[str, str], extra_keys: list[str]
) -> None:
    """Verifies complete interpolation when keys exist, and exception on missing keys."""
    # Build template using only available keys
    segments = [f"--{k}=${{{k}}}" for k in context]
    template = "run " + " ".join(segments)

    interpolated = MatrixExpansionEngine.interpolate_string(template, context)

    # Invariant: No variable placeholders remain when all keys are provided
    assert "${" not in interpolated

    # Invariant: If a missing key without default is referenced, VariableInterpolationError is raised
    missing_keys = [k for k in extra_keys if k not in context]
    if missing_keys:
        bad_template = f"run ${{{missing_keys[0]}}}"
        try:
            MatrixExpansionEngine.interpolate_string(bad_template, context)
            msg = "Expected VariableInterpolationError was not raised"
            raise AssertionError(msg)
        except VariableInterpolationError:
            pass


@given(matrix_dict_strategy())
def test_suite_compiler_determinism(matrix: dict[str, list[str]]) -> None:
    """Verifies that SuiteCompiler produces byte-for-byte deterministic JobSpecs and DAG order."""
    suite = SuiteSpec(
        id="fuzz_suite",
        matrix=matrix,
        tasks=[
            TaskSpec(
                id="task_main",
                command="echo hello",
            )
        ],
    )

    compiler_a = SuiteCompiler()
    compiler_b = SuiteCompiler()

    result_a = compiler_a.compile(suite=suite, run_id="run-fuzz")
    result_b = compiler_b.compile(suite=suite, run_id="run-fuzz")

    count_a = result_a.job_count
    count_b = result_b.job_count
    assert count_a == count_b

    order_a = result_a.topological_order()
    order_b = result_b.topological_order()
    assert order_a == order_b

    for job_a, job_b in zip(result_a.jobs, result_b.jobs, strict=True):
        id_a = job_a.id
        id_b = job_b.id
        assert id_a == id_b
        cmd_a = job_a.command
        cmd_b = job_b.command
        assert cmd_a == cmd_b
