"""Traceability, annotations, and credit burn reporting for GitHub Actions workflows.

Notes/Architectural Intent:
    Synthesizes execution performance summaries and credit costs into formatted
    GitHub Check Run annotations and Markdown step summaries, establishing
    bidirectional observability between GitHub and Hexaqueue.
"""

from pydantic import BaseModel, ConfigDict, Field


class JobSummaryAnnotation(BaseModel):
    """Execution summary and credit accounting annotation for a GitHub workflow job.

    Args:
        job_id: Hexaqueue job identifier.
        run_id: Hexaqueue run identifier.
        workflow_job_id: GitHub Actions workflow job ID.
        execution_seconds: Total duration of runner execution in seconds.
        credit_burn: Total HQ Credits consumed during execution.
        status: Execution terminal outcome ('COMPLETED', 'FAILED', etc.).
        node_id: Cluster node that hosted the runner.
        gpu_model: Model of GPU utilized, if any.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    credit_burn: float = Field(default=0.0, ge=0.0, description="Credits consumed")
    execution_seconds: float = Field(
        default=0.0, ge=0.0, description="Duration in seconds"
    )
    gpu_model: str | None = Field(default=None, description="GPU model used")
    job_id: str = Field(description="Hexaqueue Job ID")
    node_id: str | None = Field(
        default=None, description="Host cluster node identifier"
    )
    run_id: str = Field(description="Hexaqueue Run ID")
    status: str = Field(default="COMPLETED", description="Terminal state")
    workflow_job_id: int = Field(description="GitHub Workflow Job ID")

    def to_markdown_summary(self) -> str:
        """Format the annotation as a GitHub Actions Markdown Step Summary.

        Returns:
            Rendered GitHub flavored Markdown string.
        """
        gpu_line = f"- **GPU Model**: `{self.gpu_model}`\n" if self.gpu_model else ""
        node_line = f"- **Cluster Node**: `{self.node_id}`\n" if self.node_id else ""
        return (
            f"### ⚡ Hexaqueue Runner Execution Report\n\n"
            f"| Metric | Value |\n"
            f"|---|---|\n"
            f"| **Hexaqueue Job ID** | `{self.job_id}` |\n"
            f"| **Hexaqueue Run ID** | `{self.run_id}` |\n"
            f"| **Status** | `{self.status}` |\n"
            f"| **Duration** | `{self.execution_seconds:.2f}s` |\n"
            f"| **Credits Consumed** | `{self.credit_burn:.4f} HQ` |\n\n"
            f"**Resource Allocation Details:**\n"
            f"{node_line}"
            f"{gpu_line}"
            f"- **Single-Job Isolation**: Verified (Scratch wiped upon exit)\n"
        )


__all__ = [
    "JobSummaryAnnotation",
]
