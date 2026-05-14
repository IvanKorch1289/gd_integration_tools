"""Пакет ``core/feature_flags/`` — Sprint 7 OpenFeature compatibility layer.

Назначение:
    External-feature-flag providers (Flagsmith / LaunchDarkly / Unleash)
    через OpenFeature Provider Interface. Локальные runtime feature-flag
    остаются в :mod:`src.backend.core.config.features`.

    Логика fallback (Sprint 7):

    1. Если ``feature_flag.openfeature_external`` ВЫКЛЮЧЕН (default-OFF) —
       внешние providers НЕ опрашиваются, приложение использует только
       локальный ``feature_flags.<name>``.
    2. Если ВКЛЮЧЕН — сначала опрашивается external provider; при
       отсутствии ключа / ошибке возвращается локальное значение.

Экспортирует:
    FlagsmithProvider — OpenFeature-совместимый адаптер для Flagsmith.
    is_external_provider_enabled — проверка feature_flag.openfeature_external.
"""

from __future__ import annotations

from src.backend.core.feature_flags.flagsmith_provider import (
    FlagsmithProvider,
    is_external_provider_enabled,
)

__all__ = (
    "FlagsmithProvider",
    "is_external_provider_enabled",
)
