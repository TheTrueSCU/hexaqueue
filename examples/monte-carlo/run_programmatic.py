"""Example: Programmatic pipeline execution directly from Python.

Demonstrates submitting and awaiting a Monte-Carlo simulation pipeline
composed using Hexaqueue's Python domain models without writing YAML.
"""

import asyncio
import sys
from pathlib import Path

# Ensure examples/monte-carlo/src is on sys.path when executed directly
sys.path.insert(0, str(Path(__file__).parent / "src"))

from hexaqueue_cli.adapters.local import LocalClientAdapter
from hexaqueue_cli.domain.session import get_default_session
from hexaqueue_core.domain.lifecycle import RunState

from monte_carlo.infra.builder import build_monte_carlo_programmatic_pipeline


async def main() -> None:
    """Execute Monte-Carlo pipeline programmatically."""
    print("1. Building programmatic pipeline via Hexaqueue domain models...")
    submission = build_monte_carlo_programmatic_pipeline(
        run_id="monte-carlo-pure-python",
        num_paths=100,
        steps=50,
    )
    print(
        f"   Run '{submission.run_spec.id}' prepared with {len(submission.jobs)} jobs."
    )

    print("2. Starting in-process session and client adapter...")
    session = get_default_session()
    await session.start()
    client = LocalClientAdapter(session=session)

    print("3. Submitting workload...")
    report = await client.submit_run(submission)
    print(f"   Run '{report.run_id}' submitted (Total jobs: {report.total_jobs})")

    print("4. Awaiting run completion...")
    while report.state not in (RunState.DONE, RunState.BLOCKED):
        await asyncio.sleep(0.05)
        report = await client.get_run_status(report.run_id)

    print(f"✓ Run finished with state: {report.state}, outcome: {report.outcome}")
    print(
        f"   Completed: {report.completed_jobs}/{report.total_jobs}, Failed: {report.failed_jobs}"
    )

    await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
