"""S95 W4 / S96 W1 — Auth Gateway: canonical public facade для auth-логики.

S93 W3 создал ``verify_request`` public API в
``entrypoints.api.dependencies.auth_selector``. S95 W4 — ``core.auth.gateway``
фасад (стабильный import path для extensions). S96 W1 — перенёс РЕАЛЬНУЮ
implementation в ``core.auth.auth_selector`` чтобы избежать downward layer
violation (``core/ → entrypoints/``).

Архитектура (S96 W1):

* ``core.auth.auth_selector`` — canonical implementation (verifier
  registry, ``verify_request``, ``require_auth`` factory).
* ``core.auth.gateway`` — public facade (re-exports + OO ``AuthGateway``
  class с pre-configured defaults).
* ``entrypoints.api.dependencies.auth_selector`` — DEPRECATED shim
  (re-exports из ``core.auth.auth_selector``). Удалится в S99+.

Использование в extensions::

    from src.backend.core.auth.gateway import (
        AuthContext,
        AuthMethod,
        verify_request,
    )

    if __name__ == '__main__':
        # canonical: one import path, stable contract
        ctx = await verify_request(request, methods=AuthMethod.JWT)
"""
from __future__ import annotations

from src.backend.core.auth import (
    AuthContext,
    AuthMethod,
)
from src.backend.core.auth.auth_selector import (
    require_auth,
    set_default_auth,
    verify_request,
)

__all__ = (
    "AuthContext",
    "AuthGateway",
    "AuthMethod",
    "require_auth",
    "set_default_auth",
    "verify_request",
)


class AuthGateway:
    """Object-oriented AuthGateway facade.

    Позволяет extensions создавать instance с pre-configured defaults
    (например, scoped to specific route group). Production code может
    использовать module-level ``verify_request`` функцию напрямую.
    """

    __slots__ = ("_default_method",)

    def __init__(self, default_method: AuthMethod | list[AuthMethod] = AuthMethod.API_KEY) -> None:
        self._default_method = default_method

    async def verify(
        self,
        request: object,  # FastAPI Request (avoid import для type-stub)
        methods: AuthMethod | list[AuthMethod] | tuple[AuthMethod, ...] | None = None,
    ) -> AuthContext | None:
        """Verify request используя configured default methods.

        Args:
            request: FastAPI Request.
            methods: Override methods (None = use default).

        Returns:
            AuthContext при успехе, None если ни один verifier не сработал.
        """
        effective = methods if methods is not None else self._default_method
        return await verify_request(request, methods=effective)

    def require(self, methods: AuthMethod | list[AuthMethod] | None = None):
        """Factory для FastAPI dependency (overrides default).

        Usage::

            @router.get("/protected", dependencies=[Depends(gateway.require())])
            async def protected(): ...
        """
        return require_auth(methods=methods)
