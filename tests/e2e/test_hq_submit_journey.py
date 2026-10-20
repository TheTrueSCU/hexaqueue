"""User Journey HXQ-01: HPC Workload Batch Submission & Streaming Logs demo test.

Notes/Architectural Intent:
    Demonstrates end-to-end HPC batch job submission, execution monitoring,
    status inspection, and live log streaming using Hexaqueue (`hq`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from hexastack_cli.testing.narrator import CliNarrator

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app


@pytest.mark.demo
def test_hq_submit_journey(tmp_path: Path) -> None:
    """Execute and record the HPC Workload Batch Submission & Streaming Logs demo.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.

    Notes/Architectural Intent:
        Hermetically executes a multi-step batch workload against an isolated
        LocalCliSession, proving deterministic execution and streaming logs.
    """
    session = LocalCliSession(concurrency=2)
    set_default_session(session)

    # Declarative workload YAML
    workload_data = {
        "run": {"id": "hpc-genomics-pipeline", "name": "Genomics Variant Calling"},
        "jobs": [
            {
                "id": "ingest-fastq",
                "name": "ingest_sequencing_reads",
                "command": "echo '[INGEST] Loaded 2,500,000 paired-end reads from FASTQ.'",
            },
            {
                "id": "align-reads",
                "name": "bwa_mem_alignment",
                "command": "echo '[ALIGN] BWA-MEM indexed and aligned reads to reference genome.'",
                "depends_on": "ingest-fastq",
            },
        ],
    }
    workload_file = tmp_path / "genomics_workload.yaml"
    workload_file.write_text(yaml.safe_dump(workload_data), encoding="utf-8")

    repo_root = Path(__file__).resolve().parent.parent.parent
    output_dir = repo_root / "docs" / "assets" / "demos"

    narrator = CliNarrator(
        app,
        output_name="hexaqueue-workload-submission",
        output_dir=output_dir,
        bin_name="hq",
    )

    # Step 1: Submit declarative workload with --watch
    narrator.step(
        "1. Submitting declarative HPC batch workload with DAG dependency enforcement"
    )
    res_submit = narrator.run_command(["run", "submit", str(workload_file), "--watch"])
    code_submit = res_submit.exit_code
    assert code_submit == 0
    has_submit_banner = "submitted" in res_submit.stdout
    assert has_submit_banner is True
    has_complete = "Run completed with status: SUCCEEDED" in res_submit.stdout
    assert has_complete is True

    # Step 2: Query run status
    narrator.step("2. Inspecting pipeline run state and task completion status")
    res_status = narrator.run_command(["status", "hpc-genomics-pipeline"])
    code_status = res_status.exit_code
    assert code_status == 0
    has_status_title = "Run Status: hpc-genomics-pipeline" in res_status.stdout
    assert has_status_title is True
    has_succeeded = "SUCCEEDED" in res_status.stdout
    assert has_succeeded is True

    res_job_status = narrator.run_command(["status", "align-reads"])
    code_job_status = res_job_status.exit_code
    assert code_job_status == 0
    has_job_id = "align-reads" in res_job_status.stdout
    assert has_job_id is True

    # Step 3: Stream and tail job logs
    narrator.step(
        "3. Retrieving streaming execution logs and stdout chunks for individual jobs"
    )
    res_logs = narrator.run_command(["logs", "align-reads"])
    code_logs = res_logs.exit_code
    assert code_logs == 0
    has_log_content = "BWA-MEM indexed and aligned reads" in res_logs.stdout
    assert has_log_content is True

    artifacts = narrator.finish()
    if os.environ.get("RECORD_DEMO") == "1":
        vtt = artifacts.get("vtt")
        vtt_exists = vtt is not None and vtt.is_file()
        assert vtt_exists is True

        webm = artifacts.get("webm")
        webm_exists = webm is not None and webm.is_file()
        assert webm_exists is True
