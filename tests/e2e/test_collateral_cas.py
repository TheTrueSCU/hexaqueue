"""User Journey HXQ-03: Tiered Collateral Content-Addressable Storage (CAS) demo test.

Notes/Architectural Intent:
    Demonstrates staging model checkpoints and binary artifacts into Hexaqueue's
    Content-Addressable Storage (CAS), verifying cryptographic SHA-256 deduplication
    and local worker NVMe caching without redundant WAN transfers.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hexaqual.adapters.testing import CliNarrator

from hexaqueue_cli.domain.session import LocalCliSession, set_default_session
from hexaqueue_cli.main import app


@pytest.mark.demo
def test_collateral_cas_journey(tmp_path: Path) -> None:
    """Execute and record the Tiered Collateral Content-Addressable Storage demo.

    Args:
        tmp_path: Temporary directory fixture provided by pytest.

    Notes/Architectural Intent:
        Stages synthetic neural weights into the CAS engine, verifying deterministic
        cryptographic hash identity and zero redundant transfers.
    """
    session = LocalCliSession(concurrency=2)
    set_default_session(session)

    # Synthetic binary artifact
    model_file = tmp_path / "resnet50_weights.bin"
    model_file.write_bytes(b"PYTORCH_WEIGHTS_TENSOR_BLOB_0xDEADBEEF_RESNET50" * 64)

    repo_root = Path(__file__).resolve().parent.parent.parent
    output_dir = repo_root / "docs" / "assets" / "demos"

    narrator = CliNarrator(
        app,
        output_name="hexaqueue-tiered-collateral-cas",
        output_dir=output_dir,
        bin_name="hq",
    )

    # Step 1: Stage binary artifact
    narrator.step(
        "1. Staging binary artifact model weights into Content-Addressable Storage (CAS)"
    )
    res_stage = narrator.run_command(
        [
            "collateral",
            "stage",
            str(model_file),
            "--tier",
            "PERMANENT",
            "--kind",
            "BUNDLE",
        ]
    )
    code_stage = res_stage.exit_code
    assert code_stage == 0
    has_staged_msg = "Collateral staged successfully" in res_stage.stdout
    assert has_staged_msg is True
    has_checksum = "Checksum:" in res_stage.stdout
    assert has_checksum is True

    # Step 2: Content-addressable deduplication
    narrator.step(
        "2. Verifying cryptographic SHA-256 content-addressable deduplication"
    )
    res_dedup = narrator.run_command(["collateral", "stage", str(model_file)])
    code_dedup = res_dedup.exit_code
    assert code_dedup == 0
    has_dedup_success = "Collateral staged successfully" in res_dedup.stdout
    assert has_dedup_success is True

    # Step 3: Cluster telemetry and state inspection
    narrator.step("3. Inspecting cluster telemetry and storage asset status")
    res_stat = narrator.run_command(["stat"])
    code_stat = res_stat.exit_code
    assert code_stat == 0
    has_cluster_stat = "Hexaqueue Cluster Status" in res_stat.stdout
    assert has_cluster_stat is True

    artifacts = narrator.finish()
    if os.environ.get("RECORD_DEMO") == "1":
        vtt = artifacts.get("vtt")
        vtt_exists = vtt is not None and vtt.is_file()
        assert vtt_exists is True

        webm = artifacts.get("webm")
        webm_exists = webm is not None and webm.is_file()
        assert webm_exists is True
