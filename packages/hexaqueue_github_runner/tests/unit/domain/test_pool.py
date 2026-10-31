"""Unit tests for runner pool domain models."""

from hexaqueue_github_runner.domain.pool import (
    RunnerPoolState,
    WarmPoolConfig,
    WarmPoolRunner,
)


def test_warm_pool_config() -> None:
    """Test warm pool configuration."""
    cfg = WarmPoolConfig(
        pool_id="fast-ci",
        labels=["self-hosted", "fast"],
        min_idle=3,
        max_capacity=10,
    )
    res_id = cfg.pool_id
    assert res_id == "fast-ci"
    res_min = cfg.min_idle
    assert res_min == 3


def test_warm_pool_runner() -> None:
    """Test warm pool runner instance."""
    runner = WarmPoolRunner(
        runner_id=500,
        runner_name="runner-pool-1",
        pool_id="fast-ci",
        state=RunnerPoolState.IDLE,
    )
    res_state = runner.state
    assert res_state == RunnerPoolState.IDLE
    res_name = runner.runner_name
    assert res_name == "runner-pool-1"
