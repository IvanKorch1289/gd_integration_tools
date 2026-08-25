"""Mobile JWT verifier (ADR-0262 / ADR-0264).

Provides JWT-based authentication for mobile clients. Wraps the existing
``JwtBackend`` and adds mobile-specific claim validation:
- ``device_id``: UUID v4 format
- ``tenant_id``: matches TenantContext
- ``jti``: unique token identifier (used for revocation in Phase 2)
- ``iss``: in configured whitelist
- ``aud``: matches configured audience
- ``exp`` / ``nbf``: validated by JwtBackend

Phase 1 (cycle 261): skeleton + feature-flag gated wiring.
Phase 2 (S46 W2): revocation + per-device rate limit.
Phase 3 (S46 W3): OWASP JWT checklist review + integration tests.

Usage (when ``mobile_jwt_enabled`` flag is ON)::

    from src.backend.core.auth.mobile_jwt import MobileJwtVerifier

    verifier = MobileJwtVerifier(
        backend=jwt_backend,
        issuer_whitelist=["gd-mobile-prod", "gd-mobile-staging"],
        audience="gd-mobile-api",
    )
    context = await verifier.verify(token)  # raises JwtVerificationError
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from src.backend.core.auth.jwt_backend import JwtBackend, JwtVerificationError


@dataclass(frozen=True)
class MobileAuthContext:
    """Authenticated mobile client context returned by MobileJwtVerifier."""

    user_id: str
    device_id: str
    tenant_id: str
    jti: str


class MobileJwtVerifier:
    """JWT verifier with mobile-specific claim validation.

    Args:
        backend: Configured JwtBackend instance (handles signature + exp/nbf).
        issuer_whitelist: Allowed ``iss`` claim values.
        audience: Expected ``aud`` claim (single string).
        clock: Optional callable returning current time (default: time.time).
            Override for testing.

    Raises:
        JwtVerificationError: Token signature invalid, expired, wrong issuer,
            wrong audience, or missing/invalid mobile-specific claims.

    """

    def __init__(
        self,
        *,
        backend: JwtBackend,
        issuer_whitelist: list[str],
        audience: str,
    ) -> None:
        if not issuer_whitelist:
            raise ValueError("issuer_whitelist must not be empty")
        if not audience:
            raise ValueError("audience must not be empty")
        self._backend = backend
        self._issuer_whitelist = issuer_whitelist
        self._audience = audience

    async def verify(self, token: str) -> MobileAuthContext:
        """Verify JWT and return mobile auth context.

        Args:
            token: Compact JWT string (without ``Bearer `` prefix).

        Returns:
            MobileAuthContext with user_id, device_id, tenant_id, jti.

        Raises:
            JwtVerificationError: On any validation failure.

        """
        if not token or not isinstance(token, str):
            raise JwtVerificationError("Token must be non-empty string")

        claims = await self._backend.decode(token)

        self._validate_issuer(claims)
        self._validate_audience(claims)
        self._validate_device_id(claims)
        self._validate_tenant_id(claims)
        self._validate_jti(claims)

        return MobileAuthContext(
            user_id=str(claims["sub"]),
            device_id=str(claims["device_id"]),
            tenant_id=str(claims["tenant_id"]),
            jti=str(claims["jti"]),
        )

    def _validate_issuer(self, claims: dict[str, Any]) -> None:
        """Check ``iss`` is in whitelist."""
        iss = claims.get("iss")
        if iss not in self._issuer_whitelist:
            raise JwtVerificationError(
                f"Invalid issuer {iss!r} (allowed: {self._issuer_whitelist})"
            )

    def _validate_audience(self, claims: dict[str, Any]) -> None:
        """Check ``aud`` matches configured audience.

        Per RFC 7519, ``aud`` may be string or list of strings.
        """
        aud = claims.get("aud")
        if isinstance(aud, str):
            aud_list = [aud]
        elif isinstance(aud, list):
            aud_list = [str(a) for a in aud]
        else:
            raise JwtVerificationError(f"Invalid aud claim type: {type(aud).__name__}")
        if self._audience not in aud_list:
            raise JwtVerificationError(
                f"Invalid audience {aud_list!r} (expected {self._audience!r})"
            )

    def _validate_device_id(self, claims: dict[str, Any]) -> None:
        """Check ``device_id`` is a valid UUID v4."""
        device_id = claims.get("device_id")
        if not device_id:
            raise JwtVerificationError("Missing device_id claim")
        try:
            parsed = uuid.UUID(str(device_id))
        except (ValueError, AttributeError, TypeError) as exc:
            raise JwtVerificationError(f"Invalid device_id format: {exc}") from exc
        if parsed.version != 4:
            raise JwtVerificationError(
                f"device_id must be UUID v4, got v{parsed.version}"
            )

    def _validate_tenant_id(self, claims: dict[str, Any]) -> None:
        """Check ``tenant_id`` is present and non-empty string."""
        tenant_id = claims.get("tenant_id")
        if not tenant_id or not isinstance(tenant_id, str):
            raise JwtVerificationError(
                "Missing or invalid tenant_id claim (must be non-empty string)"
            )

    def _validate_jti(self, claims: dict[str, Any]) -> None:
        """Check ``jti`` is present (for Phase 2 revocation)."""
        jti = claims.get("jti")
        if not jti or not isinstance(jti, str):
            raise JwtVerificationError("Missing or invalid jti claim")
