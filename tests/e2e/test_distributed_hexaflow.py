"""User Journey HXQ-04: Distributed Hexaflow DAG Orchestration on Compute Nodes.

Notes/Architectural Intent:
    Demonstrates submitting a multi-stage distributed Hexaflow workflow DAG to Hexaqueue.
    Validates decentralized step execution, persistent SQLite state checkpoints,
    step outputs, and automated Mermaid execution graph generation.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from hexaflow.domain.state import StepContext
from hexaflow.dsl.builder import Workflow
from typer.testing import CliRunner

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app

runner = CliRunner()


@pytest.mark.demo
def test_distributed_hexaflow_orchestration(tmp_path: Path) -> None:
    """Execute and verify Distributed Hexaflow DAG Orchestration on compute nodes.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.

    Notes/Architectural Intent:
        Compiles a 3-stage ETL and inference DAG, executes it across the Hexaqueue
        cluster runner engine, and verifies state transitions and Mermaid diagram output.
    """
    session = LocalCliSession(concurrency=2)
    set_default_session(session)

    db_path = tmp_path / "distributed_hexaflow.db"
    wf_script = tmp_path / "cluster_etl_pipeline.py"

    wf_code = """from __future__ import annotations

from hexaflow.domain.state import StepContext
from hexaflow.dsl.builder import Workflow

etl_flow = Workflow("cluster-etl-pipeline")

etl_flow.stage("ingest")
@etl_flow.step("fetch_shard_dataset")
def fetch_shard(ctx: StepContext) -> dict[str, int]:
    return {"shard_id": 42, "num_records": 10000}

etl_flow.stage("transform")
@etl_flow.step("normalize_features", depends_on=("fetch_shard_dataset",))
def normalize(ctx: StepContext) -> dict[str, str]:
    return {"status": "normalized", "dim": "128d"}

etl_flow.stage("evaluate")
@etl_flow.step("compute_metrics", depends_on=("normalize_features",))
def evaluate(ctx: StepContext) -> dict[str, float]:
    return {"precision": 0.965, "f1_score": 0.958}
"""
    wf_script.write_text(wf_code, encoding="utf-8")

    # Step 1: Submit Hexaflow workflow to cluster
    res_submit = runner.invoke(
        app,
        [
            "workflow",
            "submit",
            f"{wf_script}:etl_flow",
            "--db",
            str(db_path),
        ],
    )
    code_submit = res_submit.exit_code
    assert code_submit == 0
    has_submit = "Submitting workflow: cluster-etl-pipeline" in res_submit.stdout
    assert has_submit is True
    has_completed = "COMPLETED" in res_submit.stdout
    assert has_completed is True

    # Step 2: Verify step checkpoints in SQLite
    assert db_path.exists()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = [row[0] for row in cursor.fetchall()]
        has_checkpoint_table = any(
            "step" in t.lower() or "run" in t.lower() for t in tables
        )
        assert has_checkpoint_table is True

    # Step 3: Verify Mermaid DAG graph export
    flow_obj = Workflow("cluster-etl-pipeline")
    flow_obj.stage("ingest")

    @flow_obj.step("fetch_shard_dataset")
    def _s1(ctx: StepContext) -> None:
        pass

    flow_obj.stage("transform")

    @flow_obj.step("normalize_features", depends_on=("fetch_shard_dataset",))
    def _s2(ctx: StepContext) -> None:
        pass

    flow_obj.stage("evaluate")

    @flow_obj.step("compute_metrics", depends_on=("normalize_features",))
    def _s3(ctx: StepContext) -> None:
        pass

    mermaid_graph = flow_obj.to_mermaid()
    has_mermaid_header = "graph TD" in mermaid_graph or "flowchart" in mermaid_graph
    assert has_mermaid_header is True
    has_node1 = "fetch_shard_dataset" in mermaid_graph
    assert has_node1 is True
    has_node2 = "normalize_features" in mermaid_graph
    assert has_node2 is True
    has_node3 = "compute_metrics" in mermaid_graph
    assert has_node3 is True
