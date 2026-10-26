"""Performance microbenchmarks for JobSpec domain modeling and serialization.

Notes/Architectural Intent:
    Measures sub-microsecond Pydantic serialization and validation latency
    for core job specifications in the distributed scheduler pipeline.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements

if TYPE_CHECKING:
    from pytest_benchmark.fixture import BenchmarkFixture


def test_perf_job_spec_creation(benchmark: BenchmarkFixture) -> None:
    """Benchmark JobSpec instantiation and schema validation.

    Args:
        benchmark: pytest-benchmark fixture.
    """
    res = ResourceRequirements(cpus=4, ram_mb=8192)

    def create_spec() -> JobSpec:
        return JobSpec(
            id="job_bench_001",
            run_id="run_bench_root",
            name="unit-benchmark-task",
            command="pytest",
            args=["--verbose", "-n", "auto"],
            env={"ENV": "test", "PARALLEL": "true"},
            resources=res,
        )

    spec = benchmark(create_spec)
    assert spec.id == "job_bench_001"


def test_perf_job_spec_serialization(benchmark: BenchmarkFixture) -> None:
    """Benchmark JobSpec JSON serialization latency.

    Args:
        benchmark: pytest-benchmark fixture.
    """
    spec = JobSpec(
        id="job_bench_001",
        run_id="run_bench_root",
        name="unit-benchmark-task",
        command="pytest",
        args=["--verbose", "-n", "auto"],
        env={"ENV": "test", "PARALLEL": "true"},
        resources=ResourceRequirements(cpus=4, ram_mb=8192),
    )

    data = benchmark(spec.model_dump_json)
    assert len(data) > 0
