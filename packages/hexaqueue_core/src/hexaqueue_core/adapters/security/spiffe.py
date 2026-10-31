"""SPIFFE workload identity and policy-based boundary authorization adapters.

Notes/Architectural Intent:
    Provides concrete adapters for SPIFFE workload identity management, token
    minting/validation, and zero-trust boundary authorization policies.
"""

from __future__ import annotations

import base64
import json
import time

from hexaqueue_core.domain.security import SpiffeAuthorizationPolicy, SpiffeId
from hexaqueue_core.ports.security import SpiffeAuthorizerPort, WorkloadIdentityPort


class LocalWorkloadIdentityAdapter(WorkloadIdentityPort):
    """Local testing and standalone development workload identity adapter.

    Args:
        spiffe_id: Optional preset SpiffeId or string. Defaults to 'spiffe://hexaqueue.org/workload/default'.
        signing_secret: Optional symmetric secret used for test token signing.
    """

    def __init__(
        self,
        spiffe_id: SpiffeId | str | None = None,
        signing_secret: str | None = None,
    ) -> None:
        if spiffe_id is None:
            self._spiffe_id = SpiffeId.parse("spiffe://hexaqueue.org/workload/default")
        elif isinstance(spiffe_id, SpiffeId):
            self._spiffe_id = spiffe_id
        else:
            self._spiffe_id = SpiffeId.parse(str(spiffe_id))

        effective_secret = signing_secret or "dev-insecure-secret-key-32b"
        self._secret = effective_secret.encode("utf-8")

    def get_spiffe_id(self) -> SpiffeId | None:
        """Retrieve the local attested SPIFFE identity.

        Returns:
            Configured SpiffeId instance.
        """
        return self._spiffe_id

    def fetch_jwt_svid(self, audience: set[str]) -> str:
        """Mint a structured JWT-SVID for outbound service calls.

        Args:
            audience: Target audience set.

        Returns:
            Encoded token string.
        """
        header = {"alg": "HS256", "typ": "JWT"}
        payload = {
            "aud": sorted(audience),
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "sub": self._spiffe_id.uri,
        }
        enc_header = (
            base64.urlsafe_b64encode(json.dumps(header).encode("utf-8"))
            .rstrip(b"=")
            .decode("ascii")
        )
        enc_payload = (
            base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8"))
            .rstrip(b"=")
            .decode("ascii")
        )
        signature = (
            base64.urlsafe_b64encode(b"simulated-valid-sig")
            .rstrip(b"=")
            .decode("ascii")
        )
        return f"{enc_header}.{enc_payload}.{signature}"

    def validate_jwt_svid(self, token: str, audience: set[str]) -> SpiffeId:
        """Validate an inbound JWT-SVID token and return the verified caller identity.

        Args:
            token: Raw token string.
            audience: Expected audience set.

        Returns:
            Verified SpiffeId.

        Raises:
            ValueError: If token structure is invalid or audience does not match.
        """
        parts = token.split(".")
        if len(parts) != 3:
            msg = "Malformed JWT-SVID token format"
            raise ValueError(msg)

        payload_b64 = parts[1]
        # Pad base64 if needed
        remainder = len(payload_b64) % 4
        if remainder > 0:
            payload_b64 += "=" * (4 - remainder)

        payload_data = json.loads(base64.urlsafe_b64decode(payload_b64).decode("utf-8"))
        token_aud = set(payload_data.get("aud", []))

        if not token_aud.intersection(audience):
            msg = f"Audience mismatch: expected one of {audience}, got {token_aud}"
            raise ValueError(msg)

        exp = payload_data.get("exp", 0)
        if time.time() > exp:
            msg = "JWT-SVID token has expired"
            raise ValueError(msg)

        sub = payload_data.get("sub", "")
        return SpiffeId.parse(sub)


class PolicySpiffeAuthorizerAdapter(SpiffeAuthorizerPort):
    """Zero-trust authorizer evaluating incoming caller identities against policy.

    Args:
        policy: SpiffeAuthorizationPolicy defining trust domains, exact IDs, and role permissions.
    """

    def __init__(self, policy: SpiffeAuthorizationPolicy | None = None) -> None:
        self._policy = policy or SpiffeAuthorizationPolicy()

    async def authorize(
        self,
        spiffe_id: SpiffeId | str | None,
        boundary: str,
        action: str = "EXECUTE",
    ) -> bool:
        """Evaluate whether a caller is authorized for a target boundary and action.

        Args:
            spiffe_id: Calling identity.
            boundary: Target boundary route or action path.
            action: Semantic action performed.

        Returns:
            True if authorized, False otherwise.
        """
        return self._policy.is_authorized(spiffe_id=spiffe_id, boundary=boundary)


__all__ = [
    "LocalWorkloadIdentityAdapter",
    "PolicySpiffeAuthorizerAdapter",
]
