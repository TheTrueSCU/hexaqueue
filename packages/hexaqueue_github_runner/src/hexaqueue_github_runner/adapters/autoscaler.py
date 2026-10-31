"""Dynamic GitHub Actions runner autoscaler implementation and test oracle.

Notes/Architectural Intent:
    Orchestrates the complete runner autoscaling lifecycle: receives webhook
    events, invokes JIT config APIs, maps labels to resource claims, and posts
    credit consumption telemetry back to GitHub. Integrates with the Federated
    Free-Tier Mesh Governor to burst zero-cost runners across cloud providers.
"""

import secrets
from datetime import UTC, datetime
from typing import Any

from hexaqueue_core.domain.config import CspProvider
from hexaqueue_core.domain.job import JobSpec
from hexaqueue_core.domain.resources import ResourceRequirements
from hexaqueue_core.ports.freetier import FederatedFreeTierGovernorPort
from hexaqueue_github_runner.domain.events import (
    GitHubWorkflowJobAction,
    GitHubWorkflowJobPayload,
)
from hexaqueue_github_runner.domain.labels import LabelTranslator
from hexaqueue_github_runner.domain.pool import (
    RunnerPoolState,
    WarmPoolConfig,
    WarmPoolRunner,
)
from hexaqueue_github_runner.domain.traceability import JobSummaryAnnotation
from hexaqueue_github_runner.ports.autoscaler import (
    GitHubRunnerAutoscalerPort,
)
from hexaqueue_github_runner.ports.client import GitHubApiClientPort


class DynamicGitHubRunnerAutoscaler(GitHubRunnerAutoscalerPort):
    """Production autoscaler dynamically provisioning ephemeral GitHub runners.

    Args:
        api_client: GitHubApiClientPort for minting JIT tokens and check runs.
        label_translator: Optional custom LabelTranslator.
        credit_rate_per_cpu_hour: Credit consumption rate per CPU-hour.
        credit_rate_per_gpu_hour: Credit consumption rate per GPU-hour.
        free_tier_governor: Optional FederatedFreeTierGovernorPort for zero-cost multi-cloud bursting.
    """

    def __init__(
        self,
        api_client: GitHubApiClientPort,
        label_translator: LabelTranslator | None = None,
        credit_rate_per_cpu_hour: float = 0.05,
        credit_rate_per_gpu_hour: float = 2.50,
        free_tier_governor: FederatedFreeTierGovernorPort | None = None,
    ) -> None:
        self.api_client = api_client
        if label_translator is not None:
            self.label_translator = label_translator
        elif free_tier_governor is not None:
            self.label_translator = LabelTranslator(default_cpus=1, default_ram_mb=1024)
        else:
            self.label_translator = LabelTranslator()
        self.credit_rate_per_cpu_hour = credit_rate_per_cpu_hour
        self.credit_rate_per_gpu_hour = credit_rate_per_gpu_hour
        self._free_tier_governor = free_tier_governor

        self._active_runners: dict[int, dict[str, Any]] = {}
        self._warm_pools: dict[str, WarmPoolConfig] = {}
        self._pool_runners: dict[str, list[WarmPoolRunner]] = {}

    @property
    def free_tier_governor(self) -> FederatedFreeTierGovernorPort | None:
        """Retrieve active federated free-tier governor, if configured."""
        return self._free_tier_governor

    def register_warm_pool(self, config: WarmPoolConfig) -> None:
        """Register a warm pool configuration."""
        if config.pool_id in self._warm_pools:
            msg = f"Warm pool '{config.pool_id}' already registered"
            raise ValueError(msg)
        self._warm_pools[config.pool_id] = config
        self._pool_runners[config.pool_id] = [
            WarmPoolRunner(
                runner_id=10000 + i,
                runner_name=f"warm-{config.pool_id}-{i}",
                pool_id=config.pool_id,
                state=RunnerPoolState.IDLE,
            )
            for i in range(config.min_idle)
        ]

    def get_active_runner_count(self) -> int:
        """Return total active ephemeral and busy warm runners."""
        return len(self._active_runners)

    def get_warm_pool_status(self, pool_id: str) -> dict[str, Any]:
        """Query status and runner metrics of a specific warm pool."""
        if pool_id not in self._warm_pools:
            msg = f"Unknown pool: {pool_id}"
            raise KeyError(msg)
        runners = self._pool_runners.get(pool_id, [])
        idle = sum(1 for r in runners if r.state == RunnerPoolState.IDLE)
        busy = sum(1 for r in runners if r.state == RunnerPoolState.BUSY)
        return {
            "busy_runners": busy,
            "idle_runners": idle,
            "pool_id": pool_id,
            "total_runners": len(runners),
        }

    async def handle_workflow_job(
        self, payload: GitHubWorkflowJobPayload
    ) -> JobSpec | None:
        """Process inbound GitHub workflow job and scale runners."""
        wf_job = payload.workflow_job
        repo = payload.repository

        if payload.action == GitHubWorkflowJobAction.QUEUED:
            return await self._handle_queued(wf_job, repo)
        if payload.action == GitHubWorkflowJobAction.IN_PROGRESS:
            self._handle_in_progress(wf_job.id)
            return None
        if payload.action == GitHubWorkflowJobAction.COMPLETED:
            await self._handle_completed(wf_job, repo)
            return None

        return None

    def _detect_preferred_csp(self, labels: list[str]) -> CspProvider | None:
        """Extract explicit Cloud Service Provider preference from runner labels."""
        for lbl in labels:
            clean = lbl.strip().upper()
            try:
                return CspProvider(clean)
            except ValueError:
                continue
        return None

    def _build_tags(self, repo_full_name: str, wf_job: Any) -> list[str]:
        """Construct deterministic indexing tags for the runner job."""
        tags = [
            "source:github",
            f"repo:{repo_full_name}",
            f"job_id:{wf_job.id}",
            "ephemeral",
        ]
        for lbl in wf_job.labels:
            clean = lbl.strip().lower()
            tags.append(f"label:{clean}")
            if clean in ("arm64", "aarch64", "x64", "x86_64"):
                tags.append(clean)
        return tags

    async def _handle_queued(
        self,
        wf_job: Any,
        repo: Any,
    ) -> JobSpec:
        """Provision JIT runner and generate JobSpec on queued action."""
        resources = self.label_translator.translate(wf_job.labels)
        token_suffix = secrets.token_hex(4)

        preferred_provider = self._detect_preferred_csp(wf_job.labels)
        run_id = f"run-gh-{repo.name}-{wf_job.run_id}"
        job_id = f"job-gh-{wf_job.id}"
        tags = self._build_tags(repo.full_name, wf_job)

        allocated_provider: CspProvider | None = None
        is_free_tier = False

        labels_lower = [lbl.lower() for lbl in wf_job.labels]
        if self._free_tier_governor is not None and "paid" not in labels_lower:
            candidate_spec = JobSpec(
                id=job_id,
                run_id=run_id,
                name=f"actions-runner-{wf_job.name}",
                command="/opt/actions-runner/run.sh",
                resources=resources,
                tags=tags,
            )
            allocated_provider = self._free_tier_governor.allocate_job(
                candidate_spec, preferred_provider=preferred_provider
            )
            is_free_tier = True
            tags.append(f"provider:{allocated_provider.value.lower()}")
            tags.append("free-tier")

        provider_part = (
            f"-{allocated_provider.value.lower()}" if allocated_provider else ""
        )
        runner_name = f"hq-gh{provider_part}-{repo.name}-{wf_job.id}-{token_suffix}"

        jit_config = await self.api_client.generate_jit_runner_config(
            owner=repo.owner,
            repo=repo.name,
            runner_name=runner_name,
            labels=wf_job.labels,
        )

        env = {
            "GITHUB_ACTIONS": "true",
            "HQ_EPHEMERAL": "1",
            "RUNNER_NAME": runner_name,
        }
        if allocated_provider is not None:
            env["HQ_CSP_PROVIDER"] = allocated_provider.value
            env["HQ_FREE_TIER"] = "1"

        job_spec = JobSpec(
            id=job_id,
            run_id=run_id,
            name=f"actions-runner-{wf_job.name}",
            command="/opt/actions-runner/run.sh",
            args=["--jitconfig", jit_config.encoded_jit_config, "--once"],
            env=env,
            resources=resources,
            tags=tags,
        )

        self._active_runners[wf_job.id] = {
            "is_free_tier": is_free_tier,
            "job_id": job_id,
            "provider": allocated_provider.value if allocated_provider else None,
            "resources": resources,
            "run_id": run_id,
            "runner_name": runner_name,
            "start_time": datetime.now(UTC),
            "status": "QUEUED",
        }

        return job_spec

    def _handle_in_progress(self, job_id: int) -> None:
        """Update active runner state to RUNNING."""
        if job_id in self._active_runners:
            self._active_runners[job_id]["status"] = "RUNNING"

    async def _handle_completed(
        self,
        wf_job: Any,
        repo: Any,
    ) -> None:
        """Teardown runner, calculate credit burn, and publish annotation."""
        tracked = self._active_runners.pop(wf_job.id, None)
        if not tracked:
            return

        is_free_tier = tracked.get("is_free_tier", False)
        provider = tracked.get("provider")

        if is_free_tier and self._free_tier_governor is not None:
            self._free_tier_governor.release_job(tracked["job_id"])

        start_time = tracked.get("start_time", datetime.now(UTC))
        now = datetime.now(UTC)
        duration_seconds = max(0.1, (now - start_time).total_seconds())

        resources: ResourceRequirements = tracked["resources"]

        if is_free_tier:
            credit_burn = 0.0
            cost_usd = 0.0
        else:
            hourly_rate = (resources.cpus * self.credit_rate_per_cpu_hour) + (
                resources.gpus * self.credit_rate_per_gpu_hour
            )
            credit_burn = max(0.0001, (duration_seconds / 3600.0) * hourly_rate)
            cost_usd = credit_burn

        annotation = JobSummaryAnnotation(
            cost_usd=cost_usd,
            credit_burn=credit_burn,
            execution_seconds=duration_seconds,
            gpu_model=resources.gpu_model,
            is_free_tier=is_free_tier,
            job_id=tracked["job_id"],
            node_id=tracked.get("runner_name"),
            provider=provider,
            run_id=tracked["run_id"],
            status=wf_job.conclusion or "COMPLETED",
            workflow_job_id=wf_job.id,
        )

        await self.api_client.post_workflow_job_annotation(
            owner=repo.owner,
            repo=repo.name,
            check_run_id=wf_job.id,
            annotation=annotation,
        )


class NaiveAutoscalerOracle:
    """Minimal reference implementation for dual-oracle differential state testing.

    Notes/Architectural Intent:
        Independent naive dictionary state machine used by Hypothesis to mathematically
        prove that DynamicGitHubRunnerAutoscaler preserves execution and queue invariants.
    """

    def __init__(self) -> None:
        self.jobs: dict[int, str] = {}
        self.active_count: int = 0
        self.active_providers: dict[int, str] = {}

    def step_queued(self, job_id: int, provider: str | None = None) -> bool:
        """Record a queued job."""
        if job_id in self.jobs:
            return False
        self.jobs[job_id] = "QUEUED"
        self.active_count += 1
        if provider:
            self.active_providers[job_id] = provider
        return True

    def step_in_progress(self, job_id: int) -> bool:
        """Transition job to in progress."""
        if job_id not in self.jobs:
            return False
        self.jobs[job_id] = "RUNNING"
        return True

    def step_completed(self, job_id: int) -> bool:
        """Transition job to completed and clean up."""
        if job_id not in self.jobs:
            return False
        del self.jobs[job_id]
        self.active_providers.pop(job_id, None)
        self.active_count -= 1
        return True


__all__ = [
    "DynamicGitHubRunnerAutoscaler",
    "NaiveAutoscalerOracle",
]
