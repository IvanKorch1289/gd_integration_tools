"""Base class для PII recognizer'ов (S218).

ADR-018 PII layer: 8 recognizers в ``services/ai/pii/recognizers/`` следуют
единому паттерну — class attributes (PATTERNS, CONTEXT) + ``__init__``
конструирующий ``PatternRecognizer``. Этот base class выносит boilerplate.

Пример (S218 — после refactor)::

    class InnRecognizer(RegexPiiRecognizer):
        SUPPORTED_ENTITY = "INN_RU"
        PATTERNS = [Pattern(name="inn_10_12_digits", regex=r"\\b\\d{10}...\\b", score=0.4)]
        CONTEXT = ["ИНН", "инн", "налогоплательщик"]

    class InheritedRecognizer(RegexPiiRecognizer):
        SUPPORTED_ENTITY = "..."
        PATTERNS = [...]
        CONTEXT = [...]

        def validate_result(self, pattern_text: str) -> bool:
            # checksum-валидация
            return _checksum_valid(pattern_text)

Ponytail: вынос class-attribute boilerplate в base class — уменьшает
8 recognizers × ~15 LOC = ~120 LOC. Без regression: PatternRecognizer
constructor принимает те же kwargs.
"""

from __future__ import annotations

from typing import ClassVar

from presidio_analyzer import Pattern, PatternRecognizer

__all__ = ("RegexPiiRecognizer",)


class RegexPiiRecognizer(PatternRecognizer):
    """Базовый class для pattern-based PII recognizer'ов.

    Subclass определяет:
    * ``SUPPORTED_ENTITY`` — entity name в Presidio (``"INN_RU"``).
    * ``LANGUAGE`` — поддерживаемый язык (default ``"ru"``).
    * ``PATTERNS`` — список :class:`presidio_analyzer.Pattern`.
    * ``CONTEXT`` — список context-boost слов.

    Subclass может override :meth:`validate_result` для checksum validation
    (INN, SNILS, CreditCase).

    Attributes:
        SUPPORTED_ENTITY: ClassVar[str] — Presidio entity type name.
        LANGUAGE: ClassVar[str] — Presidio language code.
        PATTERNS: ClassVar[list[Pattern]] — detection patterns.
        CONTEXT: ClassVar[list[str]] — context-boost keywords.
    """

    SUPPORTED_ENTITY: ClassVar[str] = ""
    LANGUAGE: ClassVar[str] = "ru"
    PATTERNS: ClassVar[list[Pattern]] = []
    CONTEXT: ClassVar[list[str]] = []

    def __init__(self) -> None:
        """Constructs PatternRecognizer через class attributes.

        Копируем PATTERNS/CONTEXT в новые list чтобы избежать shared
        state между instances (PatternRecognizer может мутировать).
        """
        super().__init__(
            supported_entity=self.SUPPORTED_ENTITY,
            supported_language=self.LANGUAGE,
            patterns=list(self.PATTERNS),
            context=list(self.CONTEXT),
        )