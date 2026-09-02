"""AuthTokenMixin — token issuance + revocation mixin (S63 M2-#1 split).

Extracted из :mod:`facade` (S164 W2 615 LOC god-object → split per
single-responsibility):
- :class:`AuthTokenMixin` (this file) — :meth:`issue_token` + :meth:`revoke_token` (~80 LOC)
- :mod:`facade` retains :class:`AuthFacade` (composition root + verify_*
  + check_permission + get_tenant)
- :class:`AuthVerifyMixin` (S62+) — verify_* methods

All methods use ``self.jwt`` property (defined в :class:`AuthFacade`) и
DI provider ``get_security_facade_provider`` (для revoke_token).

Re-exported из :mod:`facade` для backward-compat public API.
"""

from __future__ import annotations

from typing import Any


__all__ = ("AuthTokenMixin",)


class AuthTokenMixin:
    """Token operations mixin (M2-#1 split).

    Methods:
    - issue_token: mint новый JWT для subject
    - revoke_token: отозвать JWT по jti через blacklist

    Methods access self.jwt property (defined в :class:`AuthFacade`).
    MRO via mixin chain: AuthFacade(AuthVerifyMixin, AuthTokenMixin).
    """

    __slots__ = ()

    def issue_token(
        self,
        subject: str,
        *,
        tenant_id: str | None = None,
        groups: list[str] | None = None,
        capabilities: list[str] | None = None,
        expires_in: int = 3600,
        method: str = "jwt",
        extra_claims: dict[str, Any] | None = None,
    ) -> tuple[str, int]:
        """S31 Task 4: mint a new JWT for the given subject (token issuance).

        Wraps :func:`jwt_backend.encode` and merges standard claims
        (``sub``, ``tenant_id``, ``groups``, ``capabilities``, ``auth_method``).
        Existing jti is left to jwt_backend (random UUID generation).

        Args:
            subject: User identity (``sub`` claim).
            tenant_id: Tenant ID (added as custom claim).
            groups: Group names (added as ``groups`` array claim).
            capabilities: Capabilities (added as ``capabilities`` array claim).
            expires_in: TTL in seconds (default 3600).
            method: Auth method marker (``"jwt"``, ``"api_key"``, ``"saml"``, ``"mtls"``).
            extra_claims: Additional custom claims merged into the JWT.

        Returns:
            ``(token_str, expires_in)`` tuple.

        Raises:
            ValueError: If ``subject`` is empty.
            RuntimeError: If JWT encode fails (e.g., missing secret).

        """
        if not subject:
            raise ValueError("issue_token: subject must be non-empty")

        claims: dict[str, Any] = dict(extra_claims or {})
        claims["auth_method"] = method
        if tenant_id is not None:
            claims["tenant_id"] = tenant_id
        if groups is not None:
            claims["groups"] = list(groups)
        if capabilities is not None:
            claims["capabilities"] = list(capabilities)

        try:
            token, expires = self.jwt.encode(
                subject=subject, claims=claims, expires_in=expires_in
            )
            return token, expires
        except Exception as exc:
            raise RuntimeError(f"issue_token failed: {exc}") from exc

    async def revoke_token(self, jti: str) -> bool:
        """S31 Task 4: revoke a JWT by jti (blacklist).

        Adds the jti to the blacklist via :class:`SecurityFacade`. Returns
        ``True`` on success. Fail-closed: any error in the blacklist layer
        is propagated as RuntimeError.

        Args:
            jti: JWT ID (``jti`` claim) to revoke.

        Returns:
            ``True`` if blacklist write succeeded.

        Raises:
            ValueError: If ``jti`` is empty.
            RuntimeError: On blacklist layer failure (fail-closed).

        """
        if not jti:
            raise ValueError("revoke_token: jti must be non-empty")
        try:
            # S48 W10: см. _is_blacklisted — DI provider вместо inline services import.
            from src.backend.core.di.providers.auth import get_security_facade_provider

            facade = get_security_facade_provider()
            await facade.blacklist_token(jti)
            return True
        except Exception as exc:
            raise RuntimeError(f"revoke_token failed: {exc}") from exc