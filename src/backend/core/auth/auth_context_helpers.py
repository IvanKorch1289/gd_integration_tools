"""AuthContext helpers (Sprint 125 W3).

Утилиты для извлечения tenant_id / groups из AuthContext.metadata.
Вынесены в отдельный модуль для переиспользования между
``require_sso_auth`` (W3) и будущими SSO-aware слоями (W4+).
"""
from __future__ import annotations

from typing import Any

__all__ = (
    "extract_tenant_id",
    "extract_user_groups",
)


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
