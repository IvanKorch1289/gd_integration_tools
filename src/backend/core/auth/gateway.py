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

import importlib
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.auth import AuthContext, AuthMethod

if TYPE_CHECKING:  # pragma: no cover — только для статического анализа (mypy)
    from src.backend.core.auth.auth_selector import (
        require_auth,
        set_default_auth,
        verify_request,
    )

#: Имя символа → модуль-канон. Ленивый re-export (PEP 562), волна 36.
#:
#: Раньше фасад eagerly импортировал канонические функции/классы, поэтому
#: его биндинги «отставали» от ``core.auth.auth_selector`` после любого
#: reload'а или monkeypatch'а канона. Из-за этого инвариант
#: «``core.auth.gateway.verify_request is
#: entrypoints...auth_selector.verify_request``» (его проверяет
#: ``tests/unit/core/auth/test_gateway_facade.py``) становился ложным —
#: order-dependent падение в CI-режиме.
#:
#: Ленивый re-export: фасад и шим всегда отдают **текущий** объект канона.
_LAZY_EXPORTS: dict[str, str] = {
    "require_auth": "src.backend.core.auth.auth_selector",
    "set_default_auth": "src.backend.core.auth.auth_selector",
    "verify_request": "src.backend.core.auth.auth_selector",
}


def _canonical(name: str) -> Any:
    """Текущий объект канонического модуля (для внутренних вызовов фасада).

    Внутри модуля глобальный поиск имени НЕ обращается к ``__getattr__``
    (PEP 562 работает только для доступа ``module.attr`` снаружи), поэтому
    собственные вызовы фасада идут через этот хелпер — он всегда отдаёт
    **актуальный** объект канона (важно после reload'а/патча канона).

    Args:
        name: Имя канонического символа (``require_auth`` и др.).

    Returns:
        Объект из ``src.backend.core.auth.auth_selector``.

    Raises:
        KeyError: Символ не входит в канонический API.

    """
    module_name = _LAZY_EXPORTS[name]
    return getattr(importlib.import_module(module_name), name)


def __getattr__(name: str) -> Any:
    """Ленивый re-export канонического API аутентификации (PEP 562).

    Args:
        name: Имя экспортируемого символа.

    Returns:
        Объект из канонического модуля.

    Raises:
        AttributeError: Символ не входит в публичный API фасада.

    """
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    # БЕЗ кэширования в globals(): кэш зафиксировал бы объект на момент
    # первого обращения, и после reload'а/патча канона фасад «отставал» бы
    # от него → инвариант «шм-объект == канон-объект» снова ломался бы.
    return getattr(importlib.import_module(module_name), name)


def __dir__() -> list[str]:
    """Список публичных символов фасада (для автодополнения)."""
    return sorted(set(globals()) | set(_LAZY_EXPORTS))


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

    def __init__(
        self, default_method: AuthMethod | list[AuthMethod] = AuthMethod.API_KEY
    ) -> None:
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
        return await _canonical("verify_request")(request, methods=effective)

    def require(
        self, methods: AuthMethod | list[AuthMethod] | None = None
    ) -> Callable[..., Any]:
        """Factory для FastAPI dependency (overrides default).

        Usage::

            @router.get("/protected", dependencies=[Depends(gateway.require())])
            async def protected(): ...

        S49 W2 fix (P0 swarm-48 #4): если ``methods=None`` — pass
        ``self._default_method`` явно (раньше передавал None → fallback на
        ``_default_auth`` global state, что позволяло silent misconfig).
        Теперь AuthGateway использует свой configured default.
        """
        effective_methods = methods if methods is not None else self._default_method
        return _canonical("require_auth")(methods=effective_methods)
