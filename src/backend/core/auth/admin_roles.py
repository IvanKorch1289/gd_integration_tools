"""Admin RBAC роли и зависимость ``require_admin`` (S13 K1 W2).

Содержит:

* :class:`AdminRole` — закрытый набор административных ролей системы;
* :func:`require_admin` — FastAPI-зависимость, проверяющая, что в
  ``AuthContext.metadata["admin_roles"]`` присутствует хотя бы одна из
  допустимых ролей. При отсутствии — поднимается :class:`AdminAuthorizationError`
  (HTTP 403).

Используется для защиты admin-endpoints в ``entrypoints/api/v1/endpoints/admin*``
и ``tech.py`` (graceful degradation switch, profile editor, parallelism report).
"""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from src.backend.core.auth import AuthContext

__all__ = (
    "AdminAuthorizationError",
    "AdminRole",
    "extract_admin_roles",
    "require_admin",
)


class AdminRole(StrEnum):
    """Закрытый набор административных ролей.

    Mapping:

    * ``SUPER_ADMIN`` — полный доступ ко всем admin-endpoints;
    * ``OPERATOR`` — переключение degradation mode, resilience profile,
      runtime ops (без management секретов и пользователей);
    * ``TENANT_ADMIN`` — admin-операции в рамках своего тенанта
      (per-tenant resilience profile override, RAG prewarm enable);
    * ``READ_ONLY`` — только GET-эндпоинты admin-инвентарей.
    """

    SUPER_ADMIN = "super_admin"
    OPERATOR = "operator"
    TENANT_ADMIN = "tenant_admin"
    READ_ONLY = "read_only"


class AdminAuthorizationError(HTTPException):
    """HTTP 403 — у actor отсутствует требуемая admin-роль."""

    def __init__(self, *, required: tuple[AdminRole, ...], actual: frozenset[AdminRole]) -> None:
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "admin_role_required",
                "required": sorted(r.value for r in required),
                "actual": sorted(r.value for r in actual),
            },
        )


def extract_admin_roles(auth_context: AuthContext | None) -> frozenset[AdminRole]:
    """Извлекает admin-роли из ``AuthContext``.

    Источники (в порядке приоритета):

    * ``metadata["admin_roles"]`` (list[str] | str) — основной канал из
      JWT-claim ``admin_roles`` / SAML group mapping / mTLS CN whitelist;
    * пустой :class:`frozenset` при отсутствии данных.
    """
    if auth_context is None:
        return frozenset()
    raw = auth_context.metadata.get("admin_roles")
    if raw is None:
        return frozenset()
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, Iterable):
        return frozenset()
    roles: set[AdminRole] = set()
    for value in raw:
        try:
            roles.add(AdminRole(str(value)))
        except ValueError:
            continue
    return frozenset(roles)


def require_admin(roles: tuple[AdminRole, ...]):
    """Фабрика FastAPI-зависимостей — требует одну из указанных ролей.

    ``SUPER_ADMIN`` имеет неявный доступ ко всем admin-endpoints.

    Использование::

        @router.patch(
            "/tech/degradation/level",
            dependencies=[Depends(require_admin((AdminRole.OPERATOR, AdminRole.SUPER_ADMIN)))],
        )
        async def patch_degradation(...):
            ...
    """
    allowed: frozenset[AdminRole] = frozenset(roles) | {AdminRole.SUPER_ADMIN}

    async def _dep(request: Request) -> AuthContext:
        ctx: AuthContext | None = getattr(request.state, "auth_context", None)
        if ctx is None:
            raise AdminAuthorizationError(required=tuple(allowed), actual=frozenset())
        actual = extract_admin_roles(ctx)
        if not actual & allowed:
            raise AdminAuthorizationError(required=tuple(allowed), actual=actual)
        return ctx

    return _dep


RequireAdmin = Annotated[AuthContext, Depends(require_admin((AdminRole.SUPER_ADMIN,)))]
