"""Unit tests for JIT runner domain models."""

from hexaqueue_github_runner.domain.jit import (
    GitHubAppCredentials,
    JitRunnerConfig,
)


def test_jit_runner_config() -> None:
    """Test JitRunnerConfig creation."""
    config = JitRunnerConfig(
        runner_id=101,
        runner_name="runner-1",
        encoded_jit_config="eyJ0ZXN0IjoxfQ==",
        os="linux",
        labels=["self-hosted", "gpu-h100"],
        single_use=True,
    )
    res_id = config.runner_id
    assert res_id == 101
    res_single = config.single_use
    assert res_single is True


def test_github_app_credentials() -> None:
    """Test GitHubAppCredentials creation."""
    creds = GitHubAppCredentials(
        app_id="123456",
        installation_id=7890,
        private_key_pem="MIIE_DUMMY_PEM_KEY_PAYLOAD",
    )
    res_app = creds.app_id
    assert res_app == "123456"
    res_inst = creds.installation_id
    assert res_inst == 7890
