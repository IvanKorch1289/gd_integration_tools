"""require_sso_auth decorator (Sprint 125 W3).

Service-level SSO session auth + groups-to-capabilities RBAC.

Использует :class:`SsoRegistry` (W2) для resolve groups→capabilities
per ADR-0054 §3.

**Fail-closed:** decorator raise :class:`RequireSsoAuthError` при:

* ``auth.method != SAML`` — только SSO-аутентифицированные запросы;
* ``metadata["tenant_id"]`` отсутствует — caller не передал tenant;
* ``metadata["groups"]`` отсутствует — IdP не вернул groups claim;
* :meth:`SsoRegistry.get` возвращает ``None`` — IdP config не найден;
* User groups не покрывают required capability.

**Propagation:** :class:`SsoRegistryError` (Vault/schema) propagate'ится
без маскирования — operator должен fix.

**Паттерн:** зеркалирует :func:`functools.wraps` для сохранения
метаданных, поддерживает только async handlers (sync handlers
должны быть обёрнуты вручную через ``asyncio.run`` если нужны).

**Use case:** admin endpoints, service-level RBAC в extensions/ —
декоратор ставится на handler в service layer'е после FastAPI
auth_selector (который заполняет ``request.state.auth_context``).

Example::

    @require_sso_capability("admin.feature_flag:write", registry)
    async def set_feature_flag(auth: AuthContext, flag: str, value: bool) -> None:
        # auth.method == SAML, auth.principal — IdP subject,
        # auth.metadata["groups"] — IdP groups claim
        ...

Wave: s125-w3-require-sso-auth
"""
from __future__ import annotations

import functools
import inspect
from typing import Any, Awaitable, Callable, TypeVar, cast

from src.backend.core.auth.auth_context_helpers import (
    extract_tenant_id,
    extract_user_groups,
)
from src.backend.core.auth.sso_registry import SsoRegistry
from src.backend.core.logging import get_logger

__all__ = (
    "RequireSsoAuthError",
    "require_sso_auth",
    "require_sso_capability",
)

_logger = get_logger(__name__)

# Type variable для wrapped handler.
_F = TypeVar("_F", bound=Callable[..., Awaitable[Any]])


class RequireSsoAuthError(PermissionError):
    """Raised when SSO auth check fails.

    Inherits from :class:`PermissionError` — HTTP layer маппит в 403.
    Для «нет auth вообще» используется 401 (handled в entrypoints).
    """


async def _resolve_user_capabilities(
    registry: SsoRegistry,
    auth: Any,
) -> list[str]:
    """Resolve user groups → capabilities через SsoRegistry.

    Args:
        registry: :class:`SsoRegistry` instance (W2).
        auth: :class:`AuthContext` (SAML).

    Returns:
        Список capability-scope'ов пользователя.

    Raises:
        RequireSsoAuthError: tenant_id missing, IdP config not found.
        SsoRegistryError: Vault/schema error (propagated).
    """
    tenant_id = extract_tenant_id(auth)
    if tenant_id is None:
        raise RequireSsoAuthError(
            "AuthContext.metadata['tenant_id'] is required for SSO auth"
        )

    idp_config = await registry.get(tenant_id)
    if idp_config is None:
        raise RequireSsoAuthError(
            f"IdP config not found for tenant '{tenant_id}'"
        )

    user_groups = extract_user_groups(auth)
    return idp_config.groups_to_capabilities.resolve(user_groups)


def require_sso_auth(
    registry: SsoRegistry,
) -> Callable[[_F], _F]:
    """Decorator factory: enforce SSO auth на handler'е.

    Handler должен принимать ``auth: AuthContext`` параметром
    (named или positional). Decorator:

    1. Валидирует ``auth.method == SAML``;
    2. Резолвит user capabilities через SsoRegistry;
    3. Запускает handler.

    Для granular RBAC используй :func:`require_sso_capability`.

    Args:
        registry: :class:`SsoRegistry` instance.

    Returns:
        Decorator wrapping async handler.

    Raises:
        RequireSsoAuthError: SSO validation failed.
        SsoRegistryError: Vault/schema error (propagated).
    """
    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            auth = _extract_auth_from_args(args, kwargs, func)
            if auth is None:
                raise RequireSsoAuthError(
                    "Handler decorated with @require_sso_auth must accept "
                    "an 'auth' parameter (AuthContext)."
                )

            if auth.method.value != "saml":
                raise RequireSsoAuthError(
                    f"SSO auth required, got method={auth.method.value!r}"
                )

            # Resolve capabilities (raises on missing tenant/IdP config).
            await _resolve_user_capabilities(registry, auth)

            return await func(*args, **kwargs)

        return cast(_F, wrapper)

    return decorator


def require_sso_capability(
    capability: str,
    registry: SsoRegistry,
) -> Callable[[_F], _F]:
    """Decorator factory: enforce SSO auth + specific capability.

    Args:
        capability: Required capability-scope (e.g. ``"admin:write"``).
        registry: :class:`SsoRegistry` instance.

    Returns:
        Decorator wrapping async handler.

    Raises:
        RequireSsoAuthError: SSO validation failed or capability missing.
        SsoRegistryError: Vault/schema error (propagated).
    """
    def decorator(func: _F) -> _F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            auth = _extract_auth_from_args(args, kwargs, func)
            if auth is None:
                raise RequireSsoAuthError(
                    "Handler decorated with @require_sso_capability must "
                    "accept an 'auth' parameter (AuthContext)."
                )

            if auth.method.value != "saml":
                raise RequireSsoAuthError(
                    f"SSO auth required, got method={auth.method.value!r}"
                )

            user_caps = await _resolve_user_capabilities(registry, auth)
            if capability not in user_caps:
                raise RequireSsoAuthError(
                    f"User lacks required capability '{capability}' "
                    f"(user has: {sorted(user_caps)})"
                )

            return await func(*args, **kwargs)

        return cast(_F, wrapper)

    return decorator


def _extract_auth_from_args(
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    func: Callable[..., Any],
) -> Any | None:
    """Locate AuthContext-подобный объект в args/kwargs.

    Поддерживает:
    * ``auth`` keyword (preferred);
    * First positional arg с type hint ``AuthContext``.

    Returns:
        AuthContext-like object или ``None`` если не найден.
    """
    # 1) Keyword «auth» (canonical).
    if "auth" in kwargs:
        return kwargs["auth"]

    # 2) First positional — try type-hint matching.
    sig = inspect.signature(func)
    params = list(sig.parameters.values())
    if args and params:
        first_param = params[0]
        if first_param.name == "auth":
            return args[0]

    # 3) Any positional with «auth» in name.
    for i, param in enumerate(params):
        if "auth" in param.name.lower() and i < len(args):
            return args[i]

    return None
