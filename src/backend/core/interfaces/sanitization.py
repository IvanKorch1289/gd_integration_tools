"""Контракты PII-санитайзинга — слой ``core/interfaces`` (S24 W1, ADR-NEW-16).

Содержит DTO-структуры, которые возвращают и принимают реализации
:class:`AISanitizerProtocol` (``infrastructure.security.ai_sanitizer.AIDataSanitizer``,
``services.ai.pii.presidio_analyzer.PresidioSanitizerAdapter``).

Вынесено сюда, чтобы устранить layer-violation: ``services/ai/pii/``
не должен импортировать ``infrastructure/security/`` для типов данных
(Clean Architecture: ``services`` зависит только от ``core/``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ("MaskingEvent", "SanitizationResult")


@dataclass(slots=True)
class MaskingEvent:
    """Событие маскировки для audit trail.

    Attributes:
        type: Тип замаскированной сущности (EMAIL/PHONE/INN/...).
        count: Количество замаскированных вхождений данного типа.
        timestamp: Unix-timestamp события.
    """

    type: str
    count: int
    timestamp: float = 0.0


@dataclass(slots=True)
class SanitizationResult:
    """Результат маскировки с возможностью обратного восстановления.

    Attributes:
        sanitized_text: Текст после маскирования (placeholder'ы вместо PII).
        replacements: Mapping ``placeholder -> original`` для restore.
        audit_events: Список событий маскирования для audit-pipeline.
    """

    sanitized_text: str
    replacements: dict[str, str] = field(default_factory=dict)
    audit_events: list[MaskingEvent] = field(default_factory=list)

    @property
    def sanitized(self) -> str:
        """Алиас sanitized_text (обратная совместимость)."""
        return self.sanitized_text

    @property
    def _mapping(self) -> dict[str, str]:
        """Алиас replacements (обратная совместимость, legacy callers)."""
        return self.replacements

    def restore(self, text: str) -> str:
        """Восстанавливает оригинальные значения по mapping."""
        result = text
        for placeholder, original in self.replacements.items():
            result = result.replace(placeholder, original)
        return result
