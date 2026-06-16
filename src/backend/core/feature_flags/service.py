"""Единая точка доступа к feature flags (Sprint 41 W5).

Предоставляет **синхронный** API поверх:

1. Runtime overrides (``RuntimeFeatureFlagOverrides``) — highest priority.
2. Static registry (``src.backend.core.config.features.feature_flags``) — default.
3. External OpenFeature provider — *placeholder для S42; сейчас no-op*.

Цель — заменить прямые обращения ``feature_flags.<name>`` на
``get_feature_flag_service().is_enabled("name")`` без ломки
существующего sync-кода. Async-пути (entrypoints, workflow) должны
читать кэш / вызывать ``await`` методы external provider'а в S42.
"""

from __future__ import annotations

from src.backend.core.config.features import feature_flags
from src.backend.core.feature_flags.runtime_overrides import get_runtime_overrides
from src.backend.core.logging import get_logger

__all__ = ("FeatureFlagService", "get_feature_flag_service")

_logger = get_logger("core.feature_flags.service")


class FeatureFlagService:
    """Синхронный resolver feature-flags с приоритетом overrides > static.

    Attributes:
        _overrides: Runtime overrides singleton.
        _static: Pydantic-settings based static registry.
    """

    __slots__ = ("_overrides", "_static")

    def __init__(self) -> None:
        self._overrides = get_runtime_overrides()
        self._static = feature_flags

    def is_enabled(
        self, flag_key: str, *, default: bool = False, tenant_id: str | None = None
    ) -> bool:
        """Вернуть boolean-значение флага.

        Lookup order:
        1. Runtime override (global / per-tenant).
        2. Static registry ``feature_flags.<flag_key>``.
        3. ``default``.
        """
        overridden = self._overrides.get(flag_key, default=None, tenant_id=tenant_id)
        if overridden is not None:
            return bool(overridden)
        return bool(getattr(self._static, flag_key, default))

    def get_string(
        self, flag_key: str, *, default: str = "", tenant_id: str | None = None
    ) -> str:
        """Вернуть string-значение флага."""
        overridden = self._overrides.get(flag_key, default=None, tenant_id=tenant_id)
        if overridden is not None:
            return str(overridden)
        value = getattr(self._static, flag_key, default)
        return str(value) if value is not None else default

    def get_int(
        self, flag_key: str, *, default: int = 0, tenant_id: str | None = None
    ) -> int:
        """Вернуть integer-значение флага."""
        overridden = self._overrides.get(flag_key, default=None, tenant_id=tenant_id)
        if overridden is not None:
            try:
                return int(overridden)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default
        value = getattr(self._static, flag_key, default)
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return default

    def has_override(self, flag_key: str, *, tenant_id: str | None = None) -> bool:
        """``True`` если флаг изменён в runtime (global или per-tenant)."""
        return self._overrides.has_override(flag_key, tenant_id=tenant_id)


# Module-level singleton — lightweight, без side-effects.
_SERVICE: FeatureFlagService | None = None


def get_feature_flag_service() -> FeatureFlagService:
    """Вернуть глобальный singleton ``FeatureFlagService``."""
    global _SERVICE  # noqa: PLW0603
    if _SERVICE is None:
        _SERVICE = FeatureFlagService()
    return _SERVICE
