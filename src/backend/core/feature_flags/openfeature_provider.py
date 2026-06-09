"""OpenFeature SDK wrapper + backend selection (Sprint 7 K1 closure).

Назначение:
    Минимальный совместимый с OpenFeature Provider Interface backbone,
    позволяющий приложению выбрать backend (InMemory / Flagsmith) через
    ENV ``FEATURE_FLAG_BACKEND`` без жёстких зависимостей от внешних SDK.

    Архитектура:

    - :class:`OpenFeatureBackend` — Protocol с 4 resolve_*-методами
      (boolean / string / integer / object).
    - :class:`InMemoryProvider` — Sprint 7 fallback, читает локальный
      реестр :mod:`src.backend.core.config.features` (тесты + dev_light).
    - :class:`FlagsmithBackend` — обёртка над
      :class:`~src.backend.core.feature_flags.flagsmith_provider.FlagsmithProvider`,
      lazy-init и graceful degradation при отсутствии external SDK.
    - :func:`get_openfeature_backend` — фабрика; читает ENV
      ``FEATURE_FLAG_BACKEND`` ("flagsmith" → FlagsmithBackend, иначе
      InMemory).

feature_flag:
    ``openfeature_flagsmith_backend`` (default-OFF). ENV
    ``FEATURE_FLAG_BACKEND=flagsmith`` переключает на external провайдер.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.backend.core.logging import get_logger

__all__ = (
    "EvaluationContext",
    "FlagsmithBackend",
    "InMemoryProvider",
    "OpenFeatureBackend",
    "create_inmemory_backend",
    "get_openfeature_backend",
    "is_flagsmith_backend_enabled",
)

_logger = get_logger("core.feature_flags.openfeature")
_ENV_BACKEND = "FEATURE_FLAG_BACKEND"
_FLAGSMITH_BACKEND_VALUE = "flagsmith"


@dataclass(slots=True)
class EvaluationContext:
    """Контекст вычисления flag (совместим с OpenFeature spec).

    Attributes:
        tenant_id: Идентификатор tenant (Flagsmith identity).
        traits: Per-tenant атрибуты (plan, region и т.п.).
    """

    tenant_id: str | None = None
    traits: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class OpenFeatureBackend(Protocol):
    """OpenFeature Provider Interface (минимальный сабсет 4 типов).

    Реализации должны быть idempotent и не падать при ошибках —
    при недоступности backend возвращать ``default``.
    """

    async def resolve_boolean_value(
        self,
        flag_key: str,
        default: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> bool:
        """Резолвит boolean flag."""

    async def resolve_string_value(
        self,
        flag_key: str,
        default: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> str:
        """Резолвит string flag."""

    async def resolve_integer_value(
        self,
        flag_key: str,
        default: int,
        evaluation_context: EvaluationContext | None = None,
    ) -> int:
        """Резолвит integer flag."""

    async def resolve_object_value(
        self,
        flag_key: str,
        default: dict[str, Any],
        evaluation_context: EvaluationContext | None = None,
    ) -> dict[str, Any]:
        """Резолвит object (JSON) flag."""


class InMemoryProvider:
    """In-memory backend на базе локального ``feature_flags.<name>``.

    Для boolean — читает значение из :mod:`src.backend.core.config.features`.
    Для остальных типов — всегда возвращает ``default`` (Sprint 7 scope:
    локальный реестр хранит только booleans).
    """

    def __init__(self, overrides: dict[str, Any] | None = None) -> None:
        """Инициализирует backend с опциональными overrides для тестов.

        Args:
            overrides: dict ``{flag_key: value}`` — приоритет над локальным
                реестром (используется в unit-тестах).
        """
        self._overrides: dict[str, Any] = dict(overrides or {})

    @property
    def metadata(self) -> dict[str, str]:
        """OpenFeature provider metadata."""
        return {"name": "InMemoryProvider", "version": "1.0.0"}

    async def resolve_boolean_value(
        self,
        flag_key: str,
        default: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> bool:
        """Boolean: ctor-overrides → runtime overrides → локальный реестр → default.

        Sprint 16 Wave 9 (CP-15): добавлен слой runtime-overrides — admin
        endpoint ``POST /admin/feature-flags/{flag}`` пишет в singleton
        :class:`RuntimeFeatureFlagOverrides`, приоритетнее статического
        реестра, но менее приоритетен ctor-overrides (нужны для тестов).
        """
        if flag_key in self._overrides:
            return bool(self._overrides[flag_key])

        from src.backend.core.feature_flags.runtime_overrides import (
            get_runtime_overrides,
        )

        tenant_id = (
            evaluation_context.tenant_id if evaluation_context is not None else None
        )
        runtime = get_runtime_overrides()
        if runtime.has_override(flag_key, tenant_id=tenant_id):
            return bool(runtime.get(flag_key, default, tenant_id=tenant_id))

        return _read_local_flag(flag_key, default)

    async def resolve_string_value(
        self,
        flag_key: str,
        default: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> str:
        """String: overrides → default (локальный реестр хранит только bool)."""
        _ = evaluation_context
        if flag_key in self._overrides:
            return str(self._overrides[flag_key])
        return default

    async def resolve_integer_value(
        self,
        flag_key: str,
        default: int,
        evaluation_context: EvaluationContext | None = None,
    ) -> int:
        """Integer: overrides → default."""
        _ = evaluation_context
        if flag_key in self._overrides:
            return int(self._overrides[flag_key])
        return default

    async def resolve_object_value(
        self,
        flag_key: str,
        default: dict[str, Any],
        evaluation_context: EvaluationContext | None = None,
    ) -> dict[str, Any]:
        """Object: overrides → default."""
        _ = evaluation_context
        if flag_key in self._overrides:
            value = self._overrides[flag_key]
            return dict(value) if isinstance(value, dict) else default
        return default

    def set_override(self, flag_key: str, value: Any) -> None:
        """Устанавливает override (для тестов)."""
        self._overrides[flag_key] = value


class FlagsmithBackend:
    """Обёртка над :class:`FlagsmithProvider` — соответствует Protocol.

    Lazy-init; при недоступности SDK или ошибках всегда возвращает default.

    Args:
        environment_key: API key Flagsmith окружения.
        api_url: Base URL Flagsmith API.
        request_timeout_seconds: Таймаут одного REST-запроса.
        fallback: backend для случаев, когда FlagsmithProvider возвращает
            default — позволяет cascade (Flagsmith → InMemory → default).
    """

    def __init__(
        self,
        environment_key: str | None = None,
        *,
        api_url: str = "https://edge.api.flagsmith.com/api/v1/",
        request_timeout_seconds: float = 2.0,
        fallback: OpenFeatureBackend | None = None,
    ) -> None:
        """Инициализирует backend; underlying FlagsmithProvider lazy."""
        self.environment_key = environment_key
        self.api_url = api_url
        self.request_timeout_seconds = request_timeout_seconds
        self.fallback = fallback or InMemoryProvider()
        self._provider: Any | None = None

    @property
    def metadata(self) -> dict[str, str]:
        """OpenFeature provider metadata."""
        return {"name": "FlagsmithBackend", "version": "1.0.0"}

    def _get_provider(self) -> Any:
        """Lazy-init underlying FlagsmithProvider."""
        if self._provider is not None:
            return self._provider
        from src.backend.core.feature_flags.flagsmith_provider import FlagsmithProvider

        self._provider = FlagsmithProvider(
            environment_key=self.environment_key,
            api_url=self.api_url,
            request_timeout_seconds=self.request_timeout_seconds,
        )
        return self._provider

    async def resolve_boolean_value(
        self,
        flag_key: str,
        default: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> bool:
        """Boolean: Flagsmith → fallback → default."""
        try:
            provider = self._get_provider()
            from src.backend.core.feature_flags.flagsmith_provider import (
                EvaluationContext as _ProviderCtx,
            )

            ctx = _coerce_ctx(evaluation_context, _ProviderCtx)
            value = await provider.resolve_boolean_value(flag_key, default, ctx)
        except Exception as exc:
            _logger.warning("FlagsmithBackend boolean fallback: %s", exc)
            return await self.fallback.resolve_boolean_value(
                flag_key, default, evaluation_context
            )
        # Если Flagsmith вернул default — даём шанс fallback.
        if value == default:
            fb = await self.fallback.resolve_boolean_value(
                flag_key, default, evaluation_context
            )
            return fb
        return bool(value)

    async def resolve_string_value(
        self,
        flag_key: str,
        default: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> str:
        """String: Flagsmith → fallback → default."""
        try:
            provider = self._get_provider()
            from src.backend.core.feature_flags.flagsmith_provider import (
                EvaluationContext as _ProviderCtx,
            )

            ctx = _coerce_ctx(evaluation_context, _ProviderCtx)
            value = await provider.resolve_string_value(flag_key, default, ctx)
        except Exception as exc:
            _logger.warning("FlagsmithBackend string fallback: %s", exc)
            return await self.fallback.resolve_string_value(
                flag_key, default, evaluation_context
            )
        if value == default:
            return await self.fallback.resolve_string_value(
                flag_key, default, evaluation_context
            )
        return str(value)

    async def resolve_integer_value(
        self,
        flag_key: str,
        default: int,
        evaluation_context: EvaluationContext | None = None,
    ) -> int:
        """Integer: Flagsmith → fallback → default."""
        try:
            provider = self._get_provider()
            from src.backend.core.feature_flags.flagsmith_provider import (
                EvaluationContext as _ProviderCtx,
            )

            ctx = _coerce_ctx(evaluation_context, _ProviderCtx)
            value = await provider.resolve_integer_value(flag_key, default, ctx)
        except Exception as exc:
            _logger.warning("FlagsmithBackend integer fallback: %s", exc)
            return await self.fallback.resolve_integer_value(
                flag_key, default, evaluation_context
            )
        if value == default:
            return await self.fallback.resolve_integer_value(
                flag_key, default, evaluation_context
            )
        return int(value)

    async def resolve_object_value(
        self,
        flag_key: str,
        default: dict[str, Any],
        evaluation_context: EvaluationContext | None = None,
    ) -> dict[str, Any]:
        """Object: Flagsmith → fallback → default."""
        try:
            provider = self._get_provider()
            from src.backend.core.feature_flags.flagsmith_provider import (
                EvaluationContext as _ProviderCtx,
            )

            ctx = _coerce_ctx(evaluation_context, _ProviderCtx)
            value = await provider.resolve_object_value(flag_key, default, ctx)
        except Exception as exc:
            _logger.warning("FlagsmithBackend object fallback: %s", exc)
            return await self.fallback.resolve_object_value(
                flag_key, default, evaluation_context
            )
        if value == default:
            return await self.fallback.resolve_object_value(
                flag_key, default, evaluation_context
            )
        return dict(value)

    async def shutdown(self) -> None:
        """Закрытие underlying провайдера."""
        if self._provider is None:
            return
        shutdown = getattr(self._provider, "shutdown", None)
        if shutdown is not None:
            try:
                await shutdown()
            except Exception as _:
                _logger.exception("FlagsmithBackend shutdown failed")
        self._provider = None


def _coerce_ctx(ctx: EvaluationContext | None, provider_cls: type[Any]) -> Any:
    """Преобразует наш EvaluationContext в provider-specific EvaluationContext.

    Args:
        ctx: Локальный контекст или None.
        provider_cls: Класс EvaluationContext из :mod:`flagsmith_provider`.

    Returns:
        Экземпляр provider_cls с теми же полями.
    """
    if ctx is None:
        return None
    return provider_cls(tenant_id=ctx.tenant_id, traits=dict(ctx.traits))


def _read_local_flag(flag_key: str, default: bool) -> bool:
    """Читает локальный реестр feature_flags.<flag_key>.

    Args:
        flag_key: Имя flag в локальном реестре.
        default: Возвращается, если реестр недоступен / нет атрибута.

    Returns:
        Значение flag или default.
    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(getattr(feature_flags, flag_key, default))
    except Exception as _:
        _logger.debug("local feature_flags недоступен, default=%s", default)
        return default


def is_flagsmith_backend_enabled() -> bool:
    """Проверяет, активирован ли Flagsmith backend.

    Returns:
        True, если ENV ``FEATURE_FLAG_BACKEND=flagsmith`` И локальный
        feature_flag ``openfeature_flagsmith_backend`` установлен в True.
    """
    if os.environ.get(_ENV_BACKEND, "").lower() != _FLAGSMITH_BACKEND_VALUE:
        return False
    return _read_local_flag("openfeature_flagsmith_backend", default=False)


def create_inmemory_backend(
    overrides: dict[str, Any] | None = None,
) -> InMemoryProvider:
    """Создаёт [InMemoryProvider] с опциональными overrides (для тестов)."""
    return InMemoryProvider(overrides=overrides)


def get_openfeature_backend(
    *,
    environment_key: str | None = None,
    inmemory_overrides: dict[str, Any] | None = None,
) -> OpenFeatureBackend:
    """Фабрика OpenFeature backend по ENV / feature_flag.

    Если ENV ``FEATURE_FLAG_BACKEND=flagsmith`` и feature_flag
    ``openfeature_flagsmith_backend=True`` — возвращает
    :class:`FlagsmithBackend`. В остальных случаях — :class:`InMemoryProvider`.

    Args:
        environment_key: API key Flagsmith (или None — будет fallback).
        inmemory_overrides: Overrides для InMemoryProvider (тесты).

    Returns:
        Реализация [OpenFeatureBackend].
    """
    if is_flagsmith_backend_enabled():
        return FlagsmithBackend(
            environment_key=environment_key
            or os.environ.get("FLAGSMITH_ENVIRONMENT_KEY"),
            fallback=InMemoryProvider(overrides=inmemory_overrides),
        )
    return InMemoryProvider(overrides=inmemory_overrides)
