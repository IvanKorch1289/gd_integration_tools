"""AuthContext helpers (Sprint 125 W3).

Утилиты для извлечения tenant_id / groups / permissions из
``AuthContext.metadata``. Вынесены в отдельный модуль для
переиспользования между ``require_sso_auth`` (W3) и будущими
SSO-aware слоями (W4+).

Sprint 1.1 (L5 Security Chain): ``extract_user_permissions`` —
источник прав для ``ExecutionContext.permissions``. Если в
``AuthContext.metadata`` уже есть ``"permissions"`` (список /
кортеж строк) — отдаём как есть. Иначе пробуем OAuth-style
``"scope"`` (строка ``"a b c"`` → префиксуем ``"scope:"``). Пусто
или отсутствует — пустой кортеж. Fail-closed downstream:
:func:`DslService.dispatch` при пустых permissions и non-empty
``pipeline.security`` рейзит ``RoutePermissionDeniedError`` через
:func:`check_route_permission`.
"""

from __future__ import annotations

from typing import Any

__all__ = ("extract_tenant_id", "extract_user_groups", "extract_user_permissions")


def extract_tenant_id(auth: Any) -> str | None:
    """Извлекает tenant_id из AuthContext.metadata.

    Args:
        auth: :class:`AuthContext` (или duck-typed объект с ``metadata``).

    Returns:
        Tenant ID string или ``None`` если отсутствует / пустой.

    """
    metadata = getattr(auth, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    tenant_id = metadata.get("tenant_id")
    if not isinstance(tenant_id, str) or not tenant_id:
        return None
    return tenant_id


def extract_user_groups(auth: Any) -> list[str]:
    """Извлекает IdP groups из AuthContext.metadata.

    Args:
        auth: :class:`AuthContext` (или duck-typed объект с ``metadata``).

    Returns:
        Список IdP groups (пустой список если отсутствуют).

    """
    metadata = getattr(auth, "metadata", None)
    if not isinstance(metadata, dict):
        return []
    groups = metadata.get("groups", [])
    if not isinstance(groups, list):
        return []
    return [g for g in groups if isinstance(g, str)]


def extract_user_permissions(auth: Any) -> tuple[str, ...]:
    """Извлекает permissions principal'а из ``AuthContext.metadata``.

    Источники (по приоритету):
    1. ``metadata["permissions"]`` — список / кортеж строк (например,
       ``["role:admin", "scope:credit.read"]``). Возвращается как есть.
    2. ``metadata["scope"]`` — строка с OAuth-style scopes
       (``"credit.read credit.write"``). Парсится по whitespace и
       каждый scope префиксуется ``"scope:"`` → нормализованный
       кортеж ``("scope:credit.read", "scope:credit.write")``.

    Args:
        auth: :class:`AuthContext` (или duck-typed объект с
            ``metadata``). ``None`` допустим — вернётся пустой кортеж.

    Returns:
        Кортеж permission-строк. Пустой кортеж если ничего не
        найдено — fail-closed downstream в
        :func:`DslService.dispatch`.
    """
    if auth is None:
        return ()
    metadata = getattr(auth, "metadata", None)
    if not isinstance(metadata, dict):
        return ()

    raw_permissions = metadata.get("permissions")
    if isinstance(raw_permissions, (list, tuple)):
        return tuple(p for p in raw_permissions if isinstance(p, str) and p)

    raw_scope = metadata.get("scope")
    if isinstance(raw_scope, str) and raw_scope.strip():
        return tuple(f"scope:{token}" for token in raw_scope.split() if token)

    return ()
