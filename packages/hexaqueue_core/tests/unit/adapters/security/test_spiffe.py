"""Unit tests for SPIFFE workload identity and authorizer adapters."""

import pytest

from hexaqueue_core.adapters.security.spiffe import (
    LocalWorkloadIdentityAdapter,
    PolicySpiffeAuthorizerAdapter,
)
from hexaqueue_core.domain.security import SpiffeAuthorizationPolicy, SpiffeId


def test_local_workload_identity_token_lifecycle() -> None:
    """Verify local workload identity fetches and validates JWT-SVID tokens."""
    adapter = LocalWorkloadIdentityAdapter(
        spiffe_id="spiffe://hexaqueue.org/sa/test-worker"
    )
    spiffe_id = adapter.get_spiffe_id()
    assert spiffe_id is not None
    assert str(spiffe_id) == "spiffe://hexaqueue.org/sa/test-worker"

    token = adapter.fetch_jwt_svid(audience={"hexaqueue-cluster"})
    assert isinstance(token, str)

    validated_id = adapter.validate_jwt_svid(
        token=token, audience={"hexaqueue-cluster"}
    )
    assert validated_id.uri == "spiffe://hexaqueue.org/sa/test-worker"


def test_local_workload_identity_audience_mismatch() -> None:
    """Verify validating a token with mismatched audience raises ValueError."""
    adapter = LocalWorkloadIdentityAdapter()
    token = adapter.fetch_jwt_svid(audience={"valid-aud"})

    with pytest.raises(ValueError, match="Audience mismatch"):
        adapter.validate_jwt_svid(token=token, audience={"wrong-aud"})


def test_local_workload_identity_malformed_token() -> None:
    """Verify malformed token raises ValueError."""
    adapter = LocalWorkloadIdentityAdapter()
    with pytest.raises(ValueError, match="Malformed JWT-SVID"):
        adapter.validate_jwt_svid(token="bad.token", audience={"aud"})


@pytest.mark.asyncio
async def test_policy_spiffe_authorizer_adapter() -> None:
    """Verify PolicySpiffeAuthorizerAdapter evaluates authorization requests."""
    policy = SpiffeAuthorizationPolicy(
        exact_spiffe_ids={"spiffe://hexaqueue.org/admin/root"}
    )
    authorizer = PolicySpiffeAuthorizerAdapter(policy=policy)

    allowed = await authorizer.authorize(
        spiffe_id=SpiffeId.parse("spiffe://hexaqueue.org/admin/root"),
        boundary="api:admin",
    )
    assert allowed is True

    denied = await authorizer.authorize(
        spiffe_id=SpiffeId.parse("spiffe://hexaqueue.org/worker/1"),
        boundary="api:admin",
    )
    assert denied is False
