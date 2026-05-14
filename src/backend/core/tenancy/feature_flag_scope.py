"""Sprint 7 Team T5 — per-tenant scope helper для feature-flags.

Назначение:
    Резолвит feature-flag с учётом текущего ``TenantContext``. Если
    ``openfeature_external`` ВКЛЮЧЕН и provider настроен — обращается
    к external provider (Flagsmith) с identity = ``tenant_id``. Иначе —
    возвращает локальное значение из :mod:`src.backend.core.config.features`.

Использование:
    .. code-block:: python

        from src.backend.core.tenancy.feature_flag_scope import (
            TenantFeatureFlagResolver,
        )

        resolver = TenantFeatureFlagResolver(provider=flagsmith_provider)
        enabled = await resolver.is_enabled("new_ui", default=False)

Архитектура:
    - core/tenancy/ слой: не импортирует infrastructure/services;
    - провайдер передаётся через DI (Protocol-аргумент);
    - провайдер опционален — без него работает только локальный реестр;
    - tenant_id берётся из ``current_tenant()`` (ContextVar).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from src.backend.core.tenancy import current_tenant

if TYPE_CHECKING:
    from src.backend.core.feature_flags.flagsmith_provider import EvaluationContext

__all__ = (
    "FeatureFlagProvider",
    "TenantFeatureFlagResolver",
)

_logger = logging.getLogger("core.tenancy.feature_flag_scope")


class FeatureFlagProvider(Protocol):
    """Минимальный contract OpenFeature-совместимого provider.

    Совместим с :class:`FlagsmithProvider`. Описан как Protocol, чтобы
    избежать жёсткой зависимости core/tenancy → core/feature_flags
    (последний может загрузиться позже в lifespan).
    """

    async def resolve_boolean_value(
        self,
        flag_key: str,
        default: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> bool:
        """Резолвит boolean flag."""
        ...

    async def resolve_string_value(
        self,
        flag_key: str,
        default: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> str:
        """Резолвит string flag."""
        ...


class TenantFeatureFlagResolver:
    """Резолвер feature-flag с per-tenant scope.

    Args:
        provider: OpenFeature-совместимый external provider (опционально).
            При None — используется только локальный
            :mod:`src.backend.core.config.features`.
        local_features: Локальный реестр feature_flag (опционально).
            По умолчанию — модульный singleton ``feature_flags``.

    Пример:
        >>> resolver = TenantFeatureFlagResolver(provider=fs_provider)
        >>> # Внутри request-context с tenant_id="acme":
        >>> await resolver.is_enabled("new_ui", default=False)
        # → Flagsmith.resolve_boolean_value("new_ui", False, ctx=acme)
    """

    __slots__ = ("provider", "_local_features")

    def __init__(
        self,
        provider: FeatureFlagProvider | None = None,
        *,
        local_features: Any | None = None,
    ) -> None:
        """Инициализирует резолвер."""
        self.provider = provider
        self._local_features = local_features

    async def is_enabled(self, flag_key: str, *, default: bool = False) -> bool:
        """Возвращает True, если ``flag_key`` включён для текущего tenant.

        Логика:

        1. Если external provider настроен И ``openfeature_external=True`` —
           опросить external provider с ``tenant_id`` из ``current_tenant()``.
        2. Иначе — вернуть локальное значение
           ``feature_flags.<flag_key>``.
        3. Если ни external, ни local не дали ответ — вернуть ``default``.

        Args:
            flag_key: Имя feature-flag (например ``"new_ui"``).
            default: Значение, если flag не найден.

        Returns:
            Значение flag.
        """
        # Сначала пробуем external provider (если включён глобальный gate).
        if self.provider is not None and self._external_enabled():
            try:
                ctx = self._build_eval_context()
                return await self.provider.resolve_boolean_value(
                    flag_key, default, ctx
                )
            except Exception:  # noqa: BLE001 — fallback на local при любых ошибках
                _logger.exception(
                    "External provider failed для %s, fallback на local",
                    flag_key,
                )
        # Local fallback.
        return self._local_lookup(flag_key, default)

    async def get_string(
        self, flag_key: str, *, default: str = ""
    ) -> str:
        """Аналогично :meth:`is_enabled`, но для string flag.

        Args:
            flag_key: Имя feature-flag.
            default: Значение, если flag не найден.

        Returns:
            Строковое значение flag.
        """
        if self.provider is not None and self._external_enabled():
            try:
                ctx = self._build_eval_context()
                return await self.provider.resolve_string_value(
                    flag_key, default, ctx
                )
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "External provider failed для %s, fallback default", flag_key
                )
        # Local flag-реестр поддерживает только bool, для string нет fallback.
        return default

    def get_current_tenant_id(self) -> str | None:
        """Возвращает tenant_id из текущего ContextVar (None вне scope)."""
        ctx = current_tenant()
        return ctx.tenant_id if ctx is not None else None

    # ── private ──────────────────────────────────────────────────────────

    def _external_enabled(self) -> bool:
        """Проверяет глобальный flag ``openfeature_external``."""
        try:
            from src.backend.core.feature_flags.flagsmith_provider import (  # noqa: PLC0415
                is_external_provider_enabled,
            )

            return is_external_provider_enabled()
        except Exception:  # noqa: BLE001
            return False

    def _build_eval_context(self) -> EvaluationContext:
        """Собирает EvaluationContext из current TenantContext."""
        from src.backend.core.feature_flags.flagsmith_provider import (  # noqa: PLC0415
            EvaluationContext,
        )

        ctx = current_tenant()
        if ctx is None:
            return EvaluationContext()
        return EvaluationContext(
            tenant_id=ctx.tenant_id,
            traits={
                "plan": ctx.plan,
                "region": ctx.region,
            },
        )

    def _local_lookup(self, flag_key: str, default: bool) -> bool:
        """Читает flag из локального ``feature_flags`` (default-safe)."""
        try:
            if self._local_features is None:
                from src.backend.core.config.features import (  # noqa: PLC0415
                    feature_flags,
                )

                self._local_features = feature_flags
            value = getattr(self._local_features, flag_key, None)
            if value is None:
                return default
            return bool(value)
        except Exception:  # noqa: BLE001
            _logger.debug("Local feature_flags lookup failed для %s", flag_key)
            return default
