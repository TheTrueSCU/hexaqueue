"""Example: Running Hexaqual test and mutation suites on a local Hexaqueue cluster.

Demonstrates submitting and monitoring test suites and mutation testing jobs
across an in-process Hexaqueue cluster (v0.1.0) using HexaqueueClusterRunnerAdapter,
with optional rootless container isolation (Podman/Docker).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from hexaqual.adapters.runners.hexaqueue_cluster import HexaqueueClusterRunnerAdapter
from hexaqual.domain.testing import MutationEngine
from rich.console import Console
from starlette.testclient import TestClient

from hexaqueue_cli.domain.session import LocalCliSession
from hexaqueue_server.adapters.api import create_server_app
from hexaqueue_server.infra.cqrs import create_hexaqueue_execution_pipeline

console = Console()


async def main() -> None:
    """Run Hexaqual test and mutation workloads on the local Hexaqueue cluster."""
    parser = argparse.ArgumentParser(
        description="Run Hexaqual on local Hexaqueue cluster."
    )
    parser.add_argument(
        "--container",
        action="store_true",
        help="Use rootless container runtime (Podman) for worker execution.",
    )
    parser.add_argument(
        "--package",
        default="packages/hexaqueue_scanner",
        help="Package directory for mutation testing demonstration.",
    )
    args = parser.parse_args()

    console.print(
        "[bold cyan]======================================================[/bold cyan]"
    )
    console.print(
        "[bold cyan]Hexaqual on Local Hexaqueue Cluster Execution Example[/bold cyan]"
    )
    console.print(
        "[bold cyan]======================================================[/bold cyan]\n"
    )

    # 1. Initialize Local Cluster Session
    if args.container:
        from hexaqueue_worker.adapters.podman import PodmanExecutionRuntimeAdapter
        from hexaqueue_worker.domain.container import PodmanConfig

        console.print(
            "📦 [yellow]Configuring worker with rootless Podman container runtime...[/yellow]"
        )
        container_runtime = PodmanExecutionRuntimeAdapter(config=PodmanConfig())
        session = LocalCliSession(concurrency=2)
        session.worker._runtime = container_runtime
    else:
        console.print(
            "⚡ [green]Configuring worker with POSIX subprocess execution runtime (v0.1.0)...[/green]"
        )
        session = LocalCliSession(concurrency=2)

    console.print("🚀 Starting in-process cluster worker daemon...")
    await session.start()

    try:
        # 2. Mount FastAPI Server & Client Adapter
        pipeline = create_hexaqueue_execution_pipeline(session.controller)
        app = create_server_app(pipeline=pipeline)

        with TestClient(app, base_url="http://local-cluster") as client:
            adapter = HexaqueueClusterRunnerAdapter(
                cluster_url="http://local-cluster",
                http_client=client,
                poll_interval=0.05,
                console=console,
            )

            # Step 1: Execute Pytest Suite via Cluster
            console.print(
                "\n[bold green]Step 1: Dispatching Pytest Suite to Cluster[/bold green]"
            )
            test_target = "packages/hexaqueue_core/tests/unit/domain/test_lifecycle.py"
            exit_code = await asyncio.to_thread(
                adapter.execute_pytest,
                test_nodes=[test_target],
                extra_args=["-o", "addopts="],
                cwd=Path(),
            )
            console.print(
                f"✓ Pytest completed on cluster with exit code: [bold]{exit_code}[/bold]"
            )
            if exit_code != 0:
                sys.exit(exit_code)

            # Step 2: Execute Mutation Testing Slice via Cluster
            console.print(
                "\n[bold green]Step 2: Dispatching Mutation Testing Slice to Cluster[/bold green]"
            )
            pkg_path = Path(args.package)
            console.print(
                f"Targeting package: [cyan]{pkg_path}[/cyan] with engine: [cyan]gremlins[/cyan]"
            )
            mut_exit_code = await asyncio.to_thread(
                adapter.run_mutation_testing,
                package_dir=pkg_path,
                engine=MutationEngine.GREMLINS,
                workers=2,
                numprocesses=2,
                batch_size=5,
            )
            console.print(
                f"✓ Mutation testing completed on cluster with exit code: [bold]{mut_exit_code}[/bold]"
            )
            if mut_exit_code != 0:
                sys.exit(mut_exit_code)

        console.print(
            "\n[bold green]🎉 All cluster execution steps completed successfully![/bold green]"
        )
    finally:
        console.print("🛑 Shutting down cluster worker daemon...")
        await session.stop()


if __name__ == "__main__":
    asyncio.run(main())
