"""Unit tests for GitHub workflow job domain events."""

from datetime import UTC, datetime

from hexaqueue_github_runner.domain.events import (
    GitHubRepository,
    GitHubWorkflowJob,
    GitHubWorkflowJobAction,
    GitHubWorkflowJobPayload,
)


def test_github_workflow_job_instantiation() -> None:
    """Test instantiating GitHubWorkflowJob entity."""
    now = datetime.now(UTC)
    job = GitHubWorkflowJob(
        id=12345,
        run_id=67890,
        workflow_name="CI",
        head_branch="main",
        head_sha="0123456789abcdef",
        name="test-matrix",
        labels=["self-hosted", "linux", "gpu-h100"],
        created_at=now,
    )
    res_id = job.id
    assert res_id == 12345
    res_labels = job.labels
    assert "gpu-h100" in res_labels
    res_status = job.status
    assert res_status == "queued"


def test_github_repository_instantiation() -> None:
    """Test instantiating GitHubRepository entity."""
    repo = GitHubRepository(
        id=999,
        name="my-repo",
        full_name="org/my-repo",
        owner="org",
        private=True,
    )
    res_owner = repo.owner
    assert res_owner == "org"
    res_private = repo.private
    assert res_private is True


def test_github_workflow_job_payload() -> None:
    """Test instantiating GitHubWorkflowJobPayload entity."""
    repo = GitHubRepository(
        id=1,
        name="repo",
        full_name="org/repo",
        owner="org",
    )
    job = GitHubWorkflowJob(
        id=10,
        run_id=20,
        head_sha="abcdef",
        name="build",
        labels=["self-hosted"],
    )
    payload = GitHubWorkflowJobPayload(
        action=GitHubWorkflowJobAction.QUEUED,
        workflow_job=job,
        repository=repo,
        installation_id=555,
        sender_login="octocat",
    )
    res_action = payload.action
    assert res_action == GitHubWorkflowJobAction.QUEUED
    res_inst = payload.installation_id
    assert res_inst == 555
