"""Пакет ``core/feature_flags/`` — Sprint 7/8A OpenFeature compatibility layer.

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

Sprint 8A K1 W6: добавлены lightweight REST-клиент Flagsmith Edge API +
backend-selection factory без жёсткой зависимости от external SDK.

Экспортирует:
    FlagsmithProvider — OpenFeature-совместимый адаптер для Flagsmith.
    is_external_provider_enabled — проверка feature_flag.openfeature_external.
    FlagsmithClient / FlagsmithFlag / FlagsmithUnavailableError — REST-клиент.
    OpenFeatureBackend / InMemoryProvider / FlagsmithBackend / EvaluationContext —
        Protocol + 2 backend реализации.
    get_openfeature_backend / is_flagsmith_backend_enabled / create_inmemory_backend.
"""

from __future__ import annotations

from src.backend.core.feature_flags.flagsmith_client import (
    FlagsmithClient,
    FlagsmithFlag,
    FlagsmithUnavailableError,
)
from src.backend.core.feature_flags.flagsmith_provider import (
    FlagsmithProvider,
    is_external_provider_enabled,
)
from src.backend.core.feature_flags.openfeature_provider import (
    EvaluationContext,
    FlagsmithBackend,
    InMemoryProvider,
    OpenFeatureBackend,
    create_inmemory_backend,
    get_openfeature_backend,
    is_flagsmith_backend_enabled,
)

__all__ = (
    "EvaluationContext",
    "FlagsmithBackend",
    "FlagsmithClient",
    "FlagsmithFlag",
    "FlagsmithProvider",
    "FlagsmithUnavailableError",
    "InMemoryProvider",
    "OpenFeatureBackend",
    "create_inmemory_backend",
    "get_openfeature_backend",
    "is_external_provider_enabled",
    "is_flagsmith_backend_enabled",
)
