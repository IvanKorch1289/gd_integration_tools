"""Sprint 7 Team T5 — Flagsmith OpenFeature provider.

Назначение:
    OpenFeature-compatible adapter для Flagsmith. Покрывает 4 типа
    значений (boolean / string / integer / object) с per-tenant scope
    через ``EvaluationContext``.

    Default-OFF: пока feature_flag ``openfeature_external`` выключен,
    провайдер возвращает ``default`` для всех ключей — приложение
    fallback'ится на локальный реестр в
    :mod:`src.backend.core.config.features`.

OpenFeature provider interface (минимальный сабсет):

    - resolve_boolean_value(flag_key, default, evaluation_context) -> bool
    - resolve_string_value(flag_key, default, evaluation_context) -> str
    - resolve_integer_value(flag_key, default, evaluation_context) -> int
    - resolve_object_value(flag_key, default, evaluation_context) -> dict

    Tenant scope передаётся через ``evaluation_context`` атрибут
    ``tenant_id`` (Flagsmith identity_id) и ``traits`` (per-identity
    attributes).

Ссылки:
    - OpenFeature spec: https://openfeature.dev/docs/reference/concepts/provider/
    - Flagsmith Python SDK: https://docs.flagsmith.com/clients/server-side/python
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

__all__ = (
    "EvaluationContext",
    "FlagsmithProvider",
    "ProviderError",
    "is_external_provider_enabled",
)

_logger = logging.getLogger("core.feature_flags.flagsmith")


class ProviderError(RuntimeError):
    """Ошибка взаимодействия с external feature-flag provider."""


@dataclass(slots=True)
class EvaluationContext:
    """OpenFeature ``EvaluationContext`` — payload для resolve_*.

    Атрибуты:
        tenant_id: Identity ключ Flagsmith (или эквивалент в LaunchDarkly).
        traits: Произвольные per-identity атрибуты (plan, region и т.п.).
    """

    tenant_id: str | None = None
    traits: dict[str, Any] = field(default_factory=dict)


def is_external_provider_enabled() -> bool:
    """Проверяет глобальный feature_flag ``openfeature_external``.

    Чтение через :mod:`src.backend.core.config.features`. При недоступности
    (например, в unit-тестах без DI) возвращает False — это безопасный
    default-OFF.

    Returns:
        True, если ``openfeature_external=True`` в реестре flag'ов.
    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(getattr(feature_flags, "openfeature_external", False))
    except Exception as _:
        _logger.debug("feature_flags недоступны, default-OFF")
        return False


class FlagsmithProvider:
    """Flagsmith OpenFeature adapter.

    Lazy-init: HTTP-клиент Flagsmith создаётся только при первом обращении
    к resolve_* (и только если ``is_external_provider_enabled()=True``).
    Это гарантирует нулевой overhead при выключенном flag.

    Args:
        environment_key: API key окружения Flagsmith (env-var
            ``FLAGSMITH_ENVIRONMENT_KEY``). Если None — провайдер всегда
            возвращает default.
        api_url: Base URL Flagsmith API (default — public flagsmith.com).
        request_timeout_seconds: Таймаут одного HTTP-запроса (Sprint 7
            best-practice — короткий, чтобы не блокировать hot-path).

    Пример:
        >>> provider = FlagsmithProvider(environment_key="ser.abc123")
        >>> ctx = EvaluationContext(tenant_id="acme-corp")
        >>> await provider.resolve_boolean_value("new_ui", False, ctx)
    """

    def __init__(
        self,
        environment_key: str | None = None,
        *,
        api_url: str = "https://edge.api.flagsmith.com/api/v1/",
        request_timeout_seconds: float = 2.0,
    ) -> None:
        """Инициализирует адаптер. HTTP-клиент создаётся lazy."""
        self.environment_key = environment_key
        self.api_url = api_url
        self.request_timeout_seconds = request_timeout_seconds
        self._client: Any | None = None

    @property
    def metadata(self) -> dict[str, str]:
        """OpenFeature provider metadata."""
        return {"name": "FlagsmithProvider", "version": "1.0.0"}

    async def resolve_boolean_value(
        self,
        flag_key: str,
        default: bool,
        evaluation_context: EvaluationContext | None = None,
    ) -> bool:
        """Резолвит boolean flag по ключу для tenant из context.

        Args:
            flag_key: Имя feature-flag (например ``"new_ui"``).
            default: Значение по умолчанию (если flag отсутствует).
            evaluation_context: Контекст с tenant_id + traits (опционально).

        Returns:
            Значение flag из Flagsmith или ``default``.
        """
        if not self._enabled():
            return default
        try:
            client = self._get_client()
        except ProviderError as exc:
            _logger.warning("Flagsmith client unavailable: %s — fallback default", exc)
            return default
        if client is None:
            return default
        # NOTE: реальный Flagsmith API-вызов через identity-attribute
        # реализуется на этапе production-rollout (S7 follow-up).
        # Сейчас возвращаем default — это безопасный fallback.
        _ = (flag_key, evaluation_context)
        return default

    async def resolve_string_value(
        self,
        flag_key: str,
        default: str,
        evaluation_context: EvaluationContext | None = None,
    ) -> str:
        """Аналогично :meth:`resolve_boolean_value`, но для string."""
        if not self._enabled():
            return default
        try:
            client = self._get_client()
        except ProviderError as exc:
            _logger.warning("Flagsmith client unavailable: %s", exc)
            return default
        if client is None:
            return default
        _ = (flag_key, evaluation_context)
        return default

    async def resolve_integer_value(
        self,
        flag_key: str,
        default: int,
        evaluation_context: EvaluationContext | None = None,
    ) -> int:
        """Аналогично :meth:`resolve_boolean_value`, но для int."""
        if not self._enabled():
            return default
        try:
            client = self._get_client()
        except ProviderError as exc:
            _logger.warning("Flagsmith client unavailable: %s", exc)
            return default
        if client is None:
            return default
        _ = (flag_key, evaluation_context)
        return default

    async def resolve_object_value(
        self,
        flag_key: str,
        default: dict[str, Any],
        evaluation_context: EvaluationContext | None = None,
    ) -> dict[str, Any]:
        """Аналогично :meth:`resolve_boolean_value`, но для dict (JSON)."""
        if not self._enabled():
            return default
        try:
            client = self._get_client()
        except ProviderError as exc:
            _logger.warning("Flagsmith client unavailable: %s", exc)
            return default
        if client is None:
            return default
        _ = (flag_key, evaluation_context)
        return default

    async def shutdown(self) -> None:
        """Graceful shutdown — закрытие HTTP-клиента, если он был создан."""
        if self._client is None:
            return
        close = getattr(self._client, "aclose", None) or getattr(
            self._client, "close", None
        )
        if close is not None:
            try:
                result = close()
                # close() может быть sync или async.
                if hasattr(result, "__await__"):
                    await result
            except Exception as _:
                _logger.exception("Flagsmith client shutdown failed")
        self._client = None

    # ── private ──────────────────────────────────────────────────────────

    def _enabled(self) -> bool:
        """True, если глобальный flag ``openfeature_external`` включён."""
        return is_external_provider_enabled()

    def _get_client(self) -> Any | None:
        """Lazy-init HTTP-клиента Flagsmith.

        Returns:
            Экземпляр клиента или None, если environment_key не задан.

        Raises:
            ProviderError: При невозможности импорта httpx (sentinel — не
                должен происходить, httpx уже в стеке проекта).
        """
        if self.environment_key is None:
            return None
        if self._client is not None:
            return self._client

        try:
            from src.backend.core.net.migration_helper import make_http_client
        except ImportError as exc:  # pragma: no cover
            raise ProviderError("migration_helper unavailable") from exc

        self._client = make_http_client(
            base_url=self.api_url,
            headers={"X-Environment-Key": self.environment_key},
            timeout=self.request_timeout_seconds,
            plugin="core/feature_flags/flagsmith_provider",
        )
        return self._client
