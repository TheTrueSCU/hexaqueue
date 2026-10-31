"""Domain models for GitHub Actions Just-In-Time (JIT) ephemeral runners.

Notes/Architectural Intent:
    Represents the JIT runner registration configuration emitted by GitHub's
    REST API, alongside authentication parameters for GitHub Apps.
"""

from pydantic import BaseModel, ConfigDict, Field


class JitRunnerConfig(BaseModel):
    """Just-In-Time (JIT) runner configuration received from GitHub API.

    Args:
        runner_id: Numeric runner ID registered in GitHub.
        runner_name: Unique runner name allocated for this job.
        encoded_jit_config: Base64-encoded JIT configuration passed to './run.sh --jitconfig'.
        os: Target operating system platform (e.g. 'linux', 'windows', 'macos').
        labels: Runner labels registered with this runner instance.
        single_use: Whether the runner will terminate after a single job execution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    encoded_jit_config: str = Field(
        description="Base64 encoded JIT config string for runner binary"
    )
    labels: list[str] = Field(
        default_factory=list, description="Labels assigned to this runner"
    )
    os: str = Field(default="linux", description="Operating system platform")
    runner_id: int = Field(description="Unique GitHub runner numeric ID")
    runner_name: str = Field(description="Registered runner name")
    single_use: bool = Field(
        default=True, description="Strict single-use ephemeral isolation flag"
    )


class GitHubAppCredentials(BaseModel):
    """Authentication configuration for GitHub App integration.

    Args:
        app_id: GitHub Application identifier.
        installation_id: Specific installation identifier for target repository/org.
        private_key_pem: PEM-encoded RSA private key for minting JWTs.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    app_id: str = Field(description="GitHub App ID")
    installation_id: int = Field(description="GitHub App Installation ID")
    private_key_pem: str = Field(description="PEM-encoded RSA private key")


__all__ = [
    "GitHubAppCredentials",
    "JitRunnerConfig",
]
