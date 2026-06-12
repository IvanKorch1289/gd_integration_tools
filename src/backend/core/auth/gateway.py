"""S95 W4 — Auth Gateway: canonical public facade для auth-логики.

S93 W3 уже создал ``verify_request`` public API в
``entrypoints.api.dependencies.auth_selector``. W4 — move canonical
import path в ``core.auth.gateway`` чтобы extensions использовали
stable public API, не entrypoints-уровень.

Архитектура:

* ``core.auth.gateway`` — stable public facade (extensions import отсюда)
* ``entrypoints.api.dependencies.auth_selector`` — implementation
  (DI-aware, holds verifier registry, can do FastAPI dependency injection)

Это thin re-export pattern: gateway импортирует из auth_selector и
пере-экспортирует. Если когда-нибудь auth_selector будет split/refactored,
extensions не сломаются (импорт через gateway остаётся стабильным).

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
from src.backend.entrypoints.api.dependencies.auth_selector import (
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
