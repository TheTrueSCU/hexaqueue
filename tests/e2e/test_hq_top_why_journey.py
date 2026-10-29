"""User Journey HXQ-02: Interactive Cluster Top & Job Explainability demo test.

Notes/Architectural Intent:
    Demonstrates cluster status inspection, compute worker node telemetry,
    hierarchical fair-share quotas, and deep scheduling decision explainability
    using Hexaqueue (`hq stat`, `hq nodes`, `hq why`, `hq explain`, `hq fairshare`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from hexaqual.adapters.testing import CliNarrator

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app


@pytest.mark.demo
def test_hq_top_why_journey(tmp_path: Path) -> None:
    """Execute and record the Interactive Cluster Top & Job Explainability demo.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.

    Notes/Architectural Intent:
        Initializes an isolated local cluster session, queues a batch workload,
        and inspects scheduler explainability and fair-share math.
    """
    session = LocalCliSession(concurrency=2)
    set_default_session(session)

    # Submit a job to explain
    workload_data = {
        "run": {"id": "ml-training-suite", "name": "Distributed LLM Pre-training"},
        "jobs": [
            {
                "id": "transformer-layer-shard",
                "name": "sharded_transformer_backward_pass",
                "command": "echo '[TRAIN] Step 1024 complete. Loss: 1.42.'",
            }
        ],
    }
    workload_file = tmp_path / "training_workload.yaml"
    workload_file.write_text(yaml.safe_dump(workload_data), encoding="utf-8")

    repo_root = Path(__file__).resolve().parent.parent.parent
    output_dir = repo_root / "docs" / "assets" / "demos"

    narrator = CliNarrator(
        app,
        output_name="hexaqueue-cluster-top-why",
        output_dir=output_dir,
        bin_name="hq",
    )

    # Prime cluster with job
    res_prime = narrator.run_command(["run", "submit", str(workload_file)])
    assert res_prime.exit_code == 0

    # Step 1: Inspect cluster status and capacity
    narrator.step(
        "1. Inspecting real-time cluster capacity, running workers, and queue backlog"
    )
    res_stat = narrator.run_command(["stat"])
    code_stat = res_stat.exit_code
    assert code_stat == 0
    has_stat_header = "Hexaqueue Cluster Status" in res_stat.stdout
    assert has_stat_header is True

    # Step 2: Query compute worker nodes and quota
    narrator.step("2. Querying compute worker nodes telemetry and resource quotas")
    res_nodes = narrator.run_command(["nodes"])
    code_nodes = res_nodes.exit_code
    assert code_nodes == 0

    res_quota = narrator.run_command(["quota"])
    code_quota = res_quota.exit_code
    assert code_quota == 0

    # Step 3: Query why job is pending / explainability
    narrator.step("3. Diagnosing job dispatch latency and queue blockers with hq why")
    res_why = narrator.run_command(["why", "transformer-layer-shard"])
    code_why = res_why.exit_code
    assert code_why == 0
    has_why_banner = "Why Pending" in res_why.stdout
    assert has_why_banner is True

    # Step 4: Deep explainability and fair-share hierarchy
    narrator.step(
        "4. Breaking down multi-factor scheduling decision report and fair-share math"
    )
    res_explain = narrator.run_command(["explain", "transformer-layer-shard"])
    code_explain = res_explain.exit_code
    assert code_explain == 0
    has_explain_report = "Scheduling Decision Report" in res_explain.stdout
    assert has_explain_report is True

    res_fairshare = narrator.run_command(["fairshare"])
    code_fairshare = res_fairshare.exit_code
    assert code_fairshare == 0
    has_hierarchy = "Root Hierarchy" in res_fairshare.stdout
    assert has_hierarchy is True

    artifacts = narrator.finish()
    if os.environ.get("RECORD_DEMO") == "1":
        vtt = artifacts.get("vtt")
        vtt_exists = vtt is not None and vtt.is_file()
        assert vtt_exists is True

        webm = artifacts.get("webm")
        webm_exists = webm is not None and webm.is_file()
        assert webm_exists is True
