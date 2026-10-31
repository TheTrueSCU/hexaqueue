"""Unit and dual-oracle property tests for DynamicGitHubRunnerAutoscaler."""

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from hexaqueue_core.adapters.freetier.governor import MultiCspFreeTierGovernor
from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.exceptions import FreeTierLimitExceededError
from hexaqueue_github_runner.adapters.autoscaler import (
    DynamicGitHubRunnerAutoscaler,
    NaiveAutoscalerOracle,
)
from hexaqueue_github_runner.adapters.github_client import (
    InMemoryGitHubApiClient,
)
from hexaqueue_github_runner.domain.events import (
    GitHubRepository,
    GitHubWorkflowJob,
    GitHubWorkflowJobAction,
    GitHubWorkflowJobPayload,
)
from hexaqueue_github_runner.domain.pool import WarmPoolConfig


def _make_payload(
    action: GitHubWorkflowJobAction,
    job_id: int,
    run_id: int = 1,
    labels: list[str] | None = None,
) -> GitHubWorkflowJobPayload:
    """Helper to create typed payload for tests."""
    repo = GitHubRepository(
        id=1,
        name="test-repo",
        full_name="org/test-repo",
        owner="org",
    )
    job = GitHubWorkflowJob(
        id=job_id,
        run_id=run_id,
        head_sha="0123456789abcdef",
        name=f"job-{job_id}",
        labels=labels or ["self-hosted", "16-cores", "gpu-h100"],
    )
    return GitHubWorkflowJobPayload(
        action=action,
        workflow_job=job,
        repository=repo,
    )


@pytest.mark.asyncio
async def test_autoscaler_lifecycle() -> None:
    """Test standard autoscaler lifecycle: queued -> in_progress -> completed."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)

    # 1. Queued
    payload_queued = _make_payload(GitHubWorkflowJobAction.QUEUED, job_id=5001)
    job_spec = await autoscaler.handle_workflow_job(payload_queued)
    assert job_spec is not None
    assert job_spec.id == "job-gh-5001"
    assert job_spec.resources.cpus == 16
    assert job_spec.resources.gpus == 1
    assert job_spec.resources.gpu_model == "h100"
    assert autoscaler.get_active_runner_count() == 1

    # 2. In Progress
    payload_in_progress = _make_payload(
        GitHubWorkflowJobAction.IN_PROGRESS, job_id=5001
    )
    res_in_prog = await autoscaler.handle_workflow_job(payload_in_progress)
    assert res_in_prog is None
    assert autoscaler.get_active_runner_count() == 1

    # 3. Completed
    payload_completed = _make_payload(GitHubWorkflowJobAction.COMPLETED, job_id=5001)
    res_completed = await autoscaler.handle_workflow_job(payload_completed)
    assert res_completed is None
    assert autoscaler.get_active_runner_count() == 0
    assert len(client.annotations) == 1
    assert client.annotations[0]["check_run_id"] == 5001


def test_warm_pool_lifecycle() -> None:
    """Test registering and querying warm pools."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)

    pool_cfg = WarmPoolConfig(
        pool_id="pool-1",
        labels=["self-hosted", "fast"],
        min_idle=3,
    )
    autoscaler.register_warm_pool(pool_cfg)

    status = autoscaler.get_warm_pool_status("pool-1")
    assert status["pool_id"] == "pool-1"
    assert status["total_runners"] == 3
    assert status["idle_runners"] == 3
    assert status["busy_runners"] == 0

    with pytest.raises(ValueError, match="already registered"):
        autoscaler.register_warm_pool(pool_cfg)

    with pytest.raises(KeyError, match="Unknown pool"):
        autoscaler.get_warm_pool_status("unknown-pool")


@given(
    actions=st.lists(
        st.tuples(
            st.sampled_from(["queued", "in_progress", "completed"]),
            st.integers(min_value=1, max_value=20),
        ),
        min_size=1,
        max_size=30,
    )
)
@settings(max_examples=25)
def test_dual_oracle_active_runner_state(actions: list[tuple[str, int]]) -> None:
    """Dual-Oracle test: prove DynamicGitHubRunnerAutoscaler active counts match NaiveAutoscalerOracle."""
    client = InMemoryGitHubApiClient()
    autoscaler = DynamicGitHubRunnerAutoscaler(api_client=client)
    oracle = NaiveAutoscalerOracle()

    async def run_scenario() -> None:
        for action_name, job_id in actions:
            if action_name == "queued":
                if job_id not in oracle.jobs:
                    payload = _make_payload(GitHubWorkflowJobAction.QUEUED, job_id)
                    await autoscaler.handle_workflow_job(payload)
                    oracle.step_queued(job_id)
            elif action_name == "in_progress":
                payload = _make_payload(GitHubWorkflowJobAction.IN_PROGRESS, job_id)
                await autoscaler.handle_workflow_job(payload)
                oracle.step_in_progress(job_id)
            elif action_name == "completed":
                payload = _make_payload(GitHubWorkflowJobAction.COMPLETED, job_id)
                await autoscaler.handle_workflow_job(payload)
                oracle.step_completed(job_id)

            # Invariant check: active runner count equivalence
            prod_count = autoscaler.get_active_runner_count()
            oracle_count = oracle.active_count
            assert prod_count == oracle_count

    asyncio.run(run_scenario())


@pytest.mark.asyncio
async def test_free_tier_autoscaler_placement_and_annotation() -> None:
    """Test autoscaler with free-tier governor: placement, zero-cost burn, and quota recycling."""
    client = InMemoryGitHubApiClient()
    governor = MultiCspFreeTierGovernor()
    autoscaler = DynamicGitHubRunnerAutoscaler(
        api_client=client, free_tier_governor=governor
    )
    assert autoscaler.free_tier_governor is governor

    # 1. Queued ARM64 job -> Should be assigned to OCI
    payload = _make_payload(
        GitHubWorkflowJobAction.QUEUED,
        job_id=6001,
        labels=["self-hosted", "arm64", "4-cores", "8gb-ram"],
    )
    job_spec = await autoscaler.handle_workflow_job(payload)
    assert job_spec is not None
    assert "provider:oci" in job_spec.tags
    assert "free-tier" in job_spec.tags
    assert job_spec.env["HQ_CSP_PROVIDER"] == "OCI"
    assert job_spec.env["HQ_FREE_TIER"] == "1"
    assert "-oci-" in job_spec.env["RUNNER_NAME"]
    assert autoscaler.get_active_runner_count() == 1

    # Invariant: Governor has 1 allocated job on OCI
    burn_report = governor.compute_federated_burn_meter()
    assert burn_report.provider_burns[CspProvider.OCI].active_jobs_count == 1
    assert burn_report.allocated_cpus == 4

    # 2. In Progress
    p_prog = _make_payload(GitHubWorkflowJobAction.IN_PROGRESS, job_id=6001)
    await autoscaler.handle_workflow_job(p_prog)
    assert autoscaler.get_active_runner_count() == 1

    # 3. Completed -> Quota recycled immediately and annotation posted
    p_comp = _make_payload(GitHubWorkflowJobAction.COMPLETED, job_id=6001)
    await autoscaler.handle_workflow_job(p_comp)
    assert autoscaler.get_active_runner_count() == 0

    # Invariant: Governor allocated slots released immediately to 0
    burn_after = governor.compute_federated_burn_meter()
    assert burn_after.provider_burns[CspProvider.OCI].active_jobs_count == 0
    assert burn_after.allocated_cpus == 0

    # Invariant: Verified $0.00 Free Tier annotation posted
    assert len(client.annotations) == 1
    annotation = client.annotations[0]["annotation"]
    assert annotation.is_free_tier is True
    assert annotation.cost_usd == 0.0
    assert annotation.credit_burn == 0.0
    assert annotation.provider == "OCI"

    summary_md = annotation.to_markdown_summary()
    assert "(Verified $0.00 Free Tier)" in summary_md
    assert "- **Cloud Provider**: `OCI`" in summary_md
    assert "- **Single-Job Isolation**: Verified" in summary_md


@pytest.mark.asyncio
async def test_multi_cloud_matrix_fan_out_bursting() -> None:
    """Test concurrent matrix fan-out bursting across all multi-CSP free tiers (10 vCPUs)."""
    client = InMemoryGitHubApiClient()
    governor = MultiCspFreeTierGovernor()
    autoscaler = DynamicGitHubRunnerAutoscaler(
        api_client=client, free_tier_governor=governor
    )

    # Matrix batch spanning across providers
    # OCI: 4 ARM vCPUs, 8GB RAM
    # Local: 2 vCPUs, 2GB RAM
    # GCP: 2 vCPUs, 1GB RAM
    # AWS: 1 vCPU, 1GB RAM
    # Azure: 1 vCPU, 1GB RAM
    # Total = 10 vCPUs
    jobs_to_schedule = [
        (7001, ["self-hosted", "arm64", "4-cores", "8gb-ram"]),  # OCI
        (7002, ["self-hosted", "local", "2-cores", "2gb-ram"]),  # Local
        (7003, ["self-hosted", "gcp", "2-cores", "1gb-ram"]),  # GCP
        (7004, ["self-hosted", "aws", "1-core", "1gb-ram"]),  # AWS
        (7005, ["self-hosted", "azure", "1-core", "1gb-ram"]),  # Azure
    ]

    dispatched: list[str] = []
    for jid, labels in jobs_to_schedule:
        payload = _make_payload(
            GitHubWorkflowJobAction.QUEUED, job_id=jid, labels=labels
        )
        spec = await autoscaler.handle_workflow_job(payload)
        assert spec is not None
        dispatched.append(spec.id)

    assert autoscaler.get_active_runner_count() == 5
    burn = governor.compute_federated_burn_meter()
    assert burn.allocated_cpus == 10  # Full free-tier mesh capacity utilized!

    # Submitting an additional job now exceeds pooled capacity
    overflow_payload = _make_payload(
        GitHubWorkflowJobAction.QUEUED, job_id=7006, labels=["self-hosted", "1-core"]
    )
    with pytest.raises(FreeTierLimitExceededError, match="exhausted"):
        await autoscaler.handle_workflow_job(overflow_payload)

    # Complete OCI job (7001), releasing 4 ARM cores
    comp_7001 = _make_payload(GitHubWorkflowJobAction.COMPLETED, job_id=7001)
    await autoscaler.handle_workflow_job(comp_7001)
    assert autoscaler.get_active_runner_count() == 4
    assert governor.compute_federated_burn_meter().allocated_cpus == 6

    # Now the overflow job requesting 2 cores on OCI succeeds
    overflow_retry = _make_payload(
        GitHubWorkflowJobAction.QUEUED,
        job_id=7006,
        labels=["self-hosted", "arm64", "2-cores"],
    )
    spec_retry = await autoscaler.handle_workflow_job(overflow_retry)
    assert spec_retry is not None
    assert "provider:oci" in spec_retry.tags

    # Teardown all remaining runners
    for jid in [7002, 7003, 7004, 7005, 7006]:
        p = _make_payload(GitHubWorkflowJobAction.COMPLETED, job_id=jid)
        await autoscaler.handle_workflow_job(p)

    assert autoscaler.get_active_runner_count() == 0
    final_burn = governor.compute_federated_burn_meter()
    assert final_burn.allocated_cpus == 0
    assert final_burn.allocated_ram_mb == 0


@pytest.mark.asyncio
async def test_zero_cost_gpu_disallowed_and_paid_override() -> None:
    """Test that free tier rejects GPUs unless 'paid' label is present."""
    client = InMemoryGitHubApiClient()
    governor = MultiCspFreeTierGovernor()
    autoscaler = DynamicGitHubRunnerAutoscaler(
        api_client=client, free_tier_governor=governor
    )

    # 1. GPU without paid -> Rejected under zero-cost invariant
    gpu_free_payload = _make_payload(
        GitHubWorkflowJobAction.QUEUED,
        job_id=8001,
        labels=["self-hosted", "gpu-h100"],
    )
    with pytest.raises(FreeTierLimitExceededError, match="Zero-Cost Invariant"):
        await autoscaler.handle_workflow_job(gpu_free_payload)

    # 2. GPU with 'paid' label -> Bypasses free tier and allocates standard runner
    gpu_paid_payload = _make_payload(
        GitHubWorkflowJobAction.QUEUED,
        job_id=8002,
        labels=["self-hosted", "paid", "gpu-h100"],
    )
    job_spec = await autoscaler.handle_workflow_job(gpu_paid_payload)
    assert job_spec is not None
    assert "free-tier" not in job_spec.tags
    assert autoscaler.get_active_runner_count() == 1

    comp_payload = _make_payload(GitHubWorkflowJobAction.COMPLETED, job_id=8002)
    await autoscaler.handle_workflow_job(comp_payload)
    assert autoscaler.get_active_runner_count() == 0
    assert len(client.annotations) == 1
    ann = client.annotations[0]["annotation"]
    assert ann.is_free_tier is False
    assert ann.credit_burn > 0.0


@given(
    actions=st.lists(
        st.tuples(
            st.sampled_from(["queued", "in_progress", "completed"]),
            st.integers(min_value=1, max_value=20),
            st.sampled_from(["arm64", "gcp", "aws", "azure", "local"]),
        ),
        min_size=1,
        max_size=30,
    )
)
@settings(max_examples=25)
def test_dual_oracle_free_tier_active_state(
    actions: list[tuple[str, int, str]],
) -> None:
    """Dual-Oracle test: prove free-tier autoscaler active count equivalence with NaiveAutoscalerOracle."""
    client = InMemoryGitHubApiClient()
    governor = MultiCspFreeTierGovernor()
    autoscaler = DynamicGitHubRunnerAutoscaler(
        api_client=client, free_tier_governor=governor
    )
    oracle = NaiveAutoscalerOracle()

    async def run_scenario() -> None:
        for action_name, job_id, provider_label in actions:
            if action_name == "queued":
                if job_id not in oracle.jobs:
                    labels = ["self-hosted", "1-core", provider_label]
                    payload = _make_payload(
                        GitHubWorkflowJobAction.QUEUED, job_id, labels=labels
                    )
                    try:
                        res = await autoscaler.handle_workflow_job(payload)
                        if res is not None:
                            oracle.step_queued(job_id, provider=provider_label)
                    except FreeTierLimitExceededError:
                        # Capacity limit reached; both remain in sync
                        pass
            elif action_name == "in_progress":
                payload = _make_payload(GitHubWorkflowJobAction.IN_PROGRESS, job_id)
                await autoscaler.handle_workflow_job(payload)
                oracle.step_in_progress(job_id)
            elif action_name == "completed":
                payload = _make_payload(GitHubWorkflowJobAction.COMPLETED, job_id)
                await autoscaler.handle_workflow_job(payload)
                oracle.step_completed(job_id)

            assert autoscaler.get_active_runner_count() == oracle.active_count

    asyncio.run(run_scenario())
