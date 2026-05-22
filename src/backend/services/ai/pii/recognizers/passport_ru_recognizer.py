"""Recognizer паспорт РФ (серия 4 цифры + номер 6 цифр) с context-валидацией.

Формат паспорта гражданина РФ: ``SSSS NNNNNN`` (серия + номер); серия отражает
код субъекта + год бланка (без жёсткой валидации). Без context-keywords любая
последовательность ``\\d{4}\\s?\\d{6}`` слишком общая (попадают телефоны,
карты, временные коды), поэтому recognizer полагается на Presidio's
context-mechanism — context_similarity_factor поднимает score только если
рядом встречаются "паспорт", "серия", "выдан", "ОВД" и т.п.
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

__all__ = ("PassportRuRecognizer",)


class PassportRuRecognizer(PatternRecognizer):
    """Presidio recognizer для паспорта РФ (контекстно-зависимый).

    Регистрирует entity type `PASSPORT_RU`. Высокий итоговый score достигается
    только при наличии context-keyword рядом — Presidio's context similarity
    boost не активируется без них (что отсекает false-positive на телефонах
    и любых 10-знач последовательностях).
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="passport_ru_series_number",
                regex=r"\b(\d{2}\s?\d{2})\s+(\d{6})\b",
                score=0.3,
            ),
        ]
        super().__init__(
            supported_entity="PASSPORT_RU",
            supported_language="ru",
            patterns=patterns,
            context=[
                "паспорт",
                "паспорта",
                "серия",
                "номер паспорта",
                "выдан",
                "ОВД",
                "ФМС",
                "УФМС",
                "код подразделения",
            ],
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate-hook: чёткий формат серия+номер.

        Реальная защита от false-positive — через context-mechanism Presidio:
        без soft-context keywords пары "1234 567890" не получают bonus score
        и фильтруются default threshold.
        """
        digits = "".join(c for c in pattern_text if c.isdigit())
        return len(digits) == 10
