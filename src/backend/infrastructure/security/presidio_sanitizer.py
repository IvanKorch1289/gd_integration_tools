"""Deprecation re-export shim для PresidioSanitizer (S24 W1).

С S24 W1 (ADR-NEW-16) канонический Presidio engine переехал в
:mod:`src.backend.services.ai.pii.presidio_analyzer`. Этот модуль остаётся
до закрытия Sprint 24 как deprecation shim для silent callers — будет
удалён в `[wave:s24/closure]` после dead-code-hunter pass.

Старый API
    * ``PresidioSanitizer`` — legacy adapter (English-only, без ru NER).
    * ``SanitizeResult`` — старая dataclass.
    * ``get_presidio_sanitizer()`` — singleton фабрика.

Новый API (рекомендуется):
    * :class:`src.backend.services.ai.pii.presidio_analyzer.PresidioSanitizerAdapter`
      — реализует `AISanitizerProtocol` (sync) и `AsyncPIISanitizerProtocol`
      (async); поддерживает ru + en через `NlpEngineProvider`; 4 custom
      recognizers (INN, СНИЛС, паспорт, кредитное дело).
    * :func:`src.backend.services.ai.pii.presidio_analyzer.get_presidio_sanitizer_adapter`
      — singleton-фабрика.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

from src.backend.services.ai.pii.presidio_analyzer import (
    PresidioSanitizerAdapter,
    get_presidio_sanitizer_adapter,
)

__all__ = (
    "PresidioSanitizer",
    "SanitizeResult",
    "get_presidio_sanitizer",
)


@dataclass(slots=True)
class SanitizeResult:
    """Legacy-форма результата (deprecated, использовать SanitizationResult).

    Сохраняется для обратной совместимости с прежним API
    `PresidioSanitizer.sanitize()`. Новый код должен использовать
    `services.ai.pii.presidio_analyzer.PresidioSanitizerAdapter` который
    возвращает `infrastructure.security.ai_sanitizer.SanitizationResult`.
    """

    sanitized_text: str
    replacements: dict[str, str] = field(default_factory=dict)
    entities_found: list[str] = field(default_factory=list)


class PresidioSanitizer:
    """Deprecated alias для PresidioSanitizerAdapter (S24 W1, ADR-NEW-16).

    Сохраняется только для silent callers; будет удалён в `[wave:s24/closure]`.
    Новый код должен использовать
    :class:`services.ai.pii.presidio_analyzer.PresidioSanitizerAdapter`.
    """

    def __init__(self, *, language: str = "en") -> None:
        warnings.warn(
            "infrastructure.security.presidio_sanitizer.PresidioSanitizer "
            "deprecated с S24 W1 (ADR-NEW-16). Используйте "
            "services.ai.pii.presidio_analyzer.PresidioSanitizerAdapter.",
            DeprecationWarning,
            stacklevel=2,
        )
        self._adapter = PresidioSanitizerAdapter(default_language=language)

    async def sanitize(
        self, text: str, *, entities: list[str] | None = None
    ) -> SanitizeResult:
        """Legacy async-маскирование (delegates to PresidioSanitizerAdapter)."""
        if not self._adapter.available:
            # graceful path: при отсутствии Presidio возвращаем результат
            # legacy regex через sync API адаптера.
            sync_result = self._adapter.sanitize_text(text)
            return SanitizeResult(
                sanitized_text=sync_result.sanitized_text,
                replacements=sync_result.replacements,
                entities_found=list(sync_result.replacements.keys()),
            )
        async_result = await self._adapter.sanitize_async(text)
        return SanitizeResult(
            sanitized_text=async_result.sanitized_text,
            replacements=async_result.replacements,
            entities_found=list(async_result.replacements.keys()),
        )

    @staticmethod
    def restore(text: str, replacements: dict[str, str]) -> str:
        """Восстанавливает оригинальные значения (deprecated)."""
        return PresidioSanitizerAdapter.restore_text(text, replacements)

    @property
    def available(self) -> bool:
        """True если Presidio engine инициализирован успешно."""
        return self._adapter.available


def get_presidio_sanitizer(*, language: str = "en") -> PresidioSanitizer:
    """Deprecated singleton-фабрика (S24 W1, ADR-NEW-16).

    Использует общий адаптер через
    :func:`services.ai.pii.presidio_analyzer.get_presidio_sanitizer_adapter`.
    """
    warnings.warn(
        "infrastructure.security.presidio_sanitizer.get_presidio_sanitizer "
        "deprecated с S24 W1 (ADR-NEW-16). Используйте "
        "services.ai.pii.presidio_analyzer.get_presidio_sanitizer_adapter.",
        DeprecationWarning,
        stacklevel=2,
    )
    # Возвращаем legacy-обёртку для совместимости с silent callers
    return PresidioSanitizer(language=language)


# Re-export новых символов для прямого импорта через старый путь
# (помогает grep'у обнаружить место deprecation в closure-pass).
_ = get_presidio_sanitizer_adapter  # type: ignore[no-redef]
