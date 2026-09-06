"""Programmatic pipeline builder using Hexaqueue domain models and expansion engine.

Notes/Architectural Intent:
    Demonstrates programmatic composition of runs, hierarchical groups, and
    parameter matrices in pure Python without writing YAML files.
"""

from pathlib import Path

from hexaqueue_core.domain.group import (
    GroupExpansionEngine,
    JobGroupSpec,
    JobTemplateSpec,
    ResourceOverrideSpec,
)
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.domain.run import RunSpec
from hexaqueue_server.domain.models import RunSubmission


def build_monte_carlo_programmatic_pipeline(
    run_id: str = "monte-carlo-python-pipeline",
    sim_dir: str = "/tmp/mc_sim_python",  # noqa: S108
    num_paths: int = 50,
    steps: int = 100,
) -> RunSubmission:
    """Build a Monte-Carlo simulation pipeline programmatically via Python models.

    Args:
        run_id: Unique identifier for the workload run.
        sim_dir: Shared temporary directory for simulation results.
        num_paths: Number of stochastic trajectory paths per regime.
        steps: Time steps simulated per trajectory path.

    Returns:
        Fully resolved RunSubmission instance with expanded jobs and dependencies.
    """
    script_path = Path(__file__).parent.parent / "cli.py"

    run_spec = RunSpec(
        id=run_id,
        name="Programmatic Monte-Carlo Simulation Pipeline",
        tags=["python", "simulation", "monte-carlo"],
    )

    simulation_group = JobGroupSpec(
        id="sim-regimes",
        name="Stochastic Simulation Regimes",
        params=[
            {
                "regime": "low_vol",
                "seed": 101,
                "drift": 0.03,
                "vol": 0.08,
                "label": "Low Volatility",
            },
            {
                "regime": "mid_vol",
                "seed": 202,
                "drift": 0.05,
                "vol": 0.18,
                "label": "Medium Volatility",
            },
            {
                "regime": "high_vol",
                "seed": 303,
                "drift": 0.08,
                "vol": 0.35,
                "label": "High Volatility & Stress",
            },
        ],
        env={
            "SIM_DIR": sim_dir,
            "SIM_SCRIPT": str(script_path.resolve()),
        },
        resources=ResourceOverrideSpec(
            cpus=1,
            ram_mb=512,
            scratch_mb=100,
            walltime_seconds=20,
        ),
        jobs=[
            JobTemplateSpec(
                id="sim-regime-{{ regime }}",
                name="Simulate {{ label }} Trajectories",
                command=(
                    f"python {{{{ SIM_SCRIPT }}}} simulate "
                    f"--regime {{{{ regime }}}} --seed {{{{ seed }}}} "
                    f"--drift {{{{ drift }}}} --vol {{{{ vol }}}} "
                    f"--paths {num_paths} --steps {steps} "
                    f"--output-dir {{{{ SIM_DIR }}}}"
                ),
            )
        ],
    )

    aggregation_job = JobTemplateSpec(
        id="smooth-and-aggregate",
        name="Surface Smoothing and Statistical Aggregation",
        command=f"python {script_path.resolve()} aggregate --input-dir {sim_dir} --regimes low_vol mid_vol high_vol --window 5",
        depends_on=["sim-regimes"],
        resources=ResourceOverrideSpec(
            cpus=1,
            ram_mb=512,
            walltime_seconds=20,
        ),
    )

    engine = GroupExpansionEngine(
        run_id=run_id,
        default_resources=ResourceRequirements(cpus=1, ram_mb=512),
    )

    resolved = engine.expand_groups(
        groups=[simulation_group],
        top_level_jobs=[aggregation_job],
    )

    return RunSubmission(
        run_spec=run_spec,
        jobs=resolved.jobs,
        dependencies=resolved.dependencies,
    )


__all__ = [
    "build_monte_carlo_programmatic_pipeline",
]
