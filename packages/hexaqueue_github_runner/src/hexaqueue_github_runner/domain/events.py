"""GitHub Actions webhook domain events and payloads.

Notes/Architectural Intent:
    Encapsulates GitHub Actions workflow_job webhook events, job states,
    and repository metadata in pure domain models with zero external
    framework dependencies.
"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class GitHubWorkflowJobAction(StrEnum):
    """Lifecycle actions emitted by GitHub Actions for workflow jobs.

    Notes/Architectural Intent:
        Matches GitHub webhook 'action' field values for workflow_job events.
    """

    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    WAITING = "waiting"


class GitHubWorkflowJob(BaseModel):
    """Specification and runtime state of a GitHub Actions workflow job.

    Args:
        id: Unique GitHub workflow job identifier.
        run_id: Parent GitHub workflow run identifier.
        workflow_name: Name of the workflow file or workflow run.
        head_branch: Branch being built or tested.
        head_sha: Git commit SHA being executed.
        status: Current status ('queued', 'in_progress', 'completed').
        conclusion: Terminal outcome if finished ('success', 'failure', 'cancelled', etc.).
        created_at: Timestamp when job was queued in UTC.
        started_at: Timestamp when job started executing in UTC.
        completed_at: Timestamp when job completed in UTC.
        name: Name of the job step or matrix cell.
        labels: Runner labels requested by 'runs-on'.
        runner_id: ID of runner assigned to this job.
        runner_name: Name of assigned runner.
        runner_group_id: ID of runner group.
        runner_group_name: Name of runner group.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(description="Unique GitHub workflow job identifier")
    run_id: int = Field(description="Parent workflow run identifier")
    workflow_name: str | None = Field(
        default=None, description="Workflow definition name"
    )
    head_branch: str | None = Field(
        default=None, description="Target branch being built"
    )
    head_sha: str = Field(description="Commit SHA being executed")
    status: str = Field(default="queued", description="Lifecycle status")
    conclusion: str | None = Field(default=None, description="Terminal outcome")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Creation timestamp UTC"
    )
    started_at: datetime | None = Field(default=None, description="Start timestamp UTC")
    completed_at: datetime | None = Field(
        default=None, description="Completion timestamp UTC"
    )
    name: str = Field(description="Job name in workflow")
    labels: list[str] = Field(
        default_factory=list, description="Requested runner labels"
    )
    runner_id: int | None = Field(default=None, description="Assigned runner ID")
    runner_name: str | None = Field(default=None, description="Assigned runner name")
    runner_group_id: int | None = Field(
        default=None, description="Assigned runner group ID"
    )
    runner_group_name: str | None = Field(
        default=None, description="Assigned runner group name"
    )


class GitHubRepository(BaseModel):
    """GitHub repository metadata accompanying webhook payloads.

    Args:
        id: GitHub repository identifier.
        name: Short repository name.
        full_name: Qualified 'owner/repo' name.
        owner: Owner or organization name.
        private: Whether repository is private.
        html_url: Web URL to repository.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: int = Field(description="GitHub repository identifier")
    name: str = Field(description="Repository name")
    full_name: str = Field(description="Qualified owner/repo slug")
    owner: str = Field(description="Owner username or organization")
    private: bool = Field(default=True, description="Private repository flag")
    html_url: str | None = Field(default=None, description="Repository HTML URL")


class GitHubWorkflowJobPayload(BaseModel):
    """Inbound GitHub workflow_job event payload.

    Args:
        action: Lifecycle action ('queued', 'in_progress', 'completed', 'waiting').
        workflow_job: Detailed workflow job entity.
        repository: Repository metadata.
        installation_id: GitHub App installation identifier if delivered via App.
        sender_login: GitHub login of event triggerer.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: GitHubWorkflowJobAction = Field(description="Workflow job event action")
    workflow_job: GitHubWorkflowJob = Field(description="Workflow job details")
    repository: GitHubRepository = Field(description="Target repository metadata")
    installation_id: int | None = Field(
        default=None, description="GitHub App installation ID"
    )
    sender_login: str | None = Field(default=None, description="Sender GitHub username")


__all__ = [
    "GitHubRepository",
    "GitHubWorkflowJob",
    "GitHubWorkflowJobAction",
    "GitHubWorkflowJobPayload",
]
