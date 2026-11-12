"""Authentication and server-side scoped principal context binding (ADR-S03, C08)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gateway.config import SYNTHETIC_BEARER_TOKENS, GatewayPolicyConfig


class AuthenticationError(Exception):
    """Raised when authentication credentials are missing, invalid, or expired."""
    def __init__(self, message: str = "Invalid or missing authentication credentials") -> None:
        super().__init__(message)
        self.code = "UNAUTHENTICATED"


@dataclass(frozen=True)
class AuthenticatedContext:
    principal_id: str
    actor_ref: str
    incident_id: str | None
    allowed_services: set[str]
    allowed_environments: set[str]
    allowed_groups: list[str]
    policy_version: str = "1.0.0"

    def has_group(self, group: str) -> bool:
        return group in self.allowed_groups

    def is_service_allowed(self, service_id: str) -> bool:
        return service_id in self.allowed_services

    def is_environment_allowed(self, environment: str) -> bool:
        return environment in self.allowed_environments


class Authenticator:
    """Validates bearer tokens out-of-band and constructs an immutable AuthenticatedContext."""

    def __init__(self, policy: GatewayPolicyConfig | None = None) -> None:
        self.policy = policy or GatewayPolicyConfig()

    def authenticate(
        self,
        token: str | None,
        incident_id: str | None = None,
        override_groups: list[str] | None = None,
        override_services: set[str] | None = None,
    ) -> AuthenticatedContext:
        """Authenticate bearer token and return authorized server context."""
        if not token:
            raise AuthenticationError("Authorization header or bearer token missing")

        clean_token = token.replace("Bearer ", "").strip()
        record = SYNTHETIC_BEARER_TOKENS.get(clean_token)
        if not record:
            raise AuthenticationError("Provided bearer token is unrecognized or revoked")

        # By default, investigator and reviewer can access all defined lab microservices
        allowed_services = override_services if override_services is not None else set(self.policy.allowed_services)
        allowed_envs = set(self.policy.allowed_environments)
        allowed_groups = override_groups if override_groups is not None else list(record["default_groups"])

        return AuthenticatedContext(
            principal_id=record["principal_id"],
            actor_ref=record["actor_ref"],
            incident_id=incident_id,
            allowed_services=allowed_services,
            allowed_environments=allowed_envs,
            allowed_groups=allowed_groups,
            policy_version=self.policy.policy_version,
        )

