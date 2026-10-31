"""Unit and dual-oracle property tests for DynamicGitHubRunnerAutoscaler."""

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

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
