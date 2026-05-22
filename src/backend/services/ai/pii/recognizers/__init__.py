"""Custom Presidio recognizers для русских domain-сущностей (S24 W1, ADR-NEW-16).

Покрывают банковские PII-entity, не покрытые встроенными Presidio-recognizers:

* :class:`InnRecognizer` — ИНН (10 или 12 цифр с checksum-валидацией по ФНС);
* :class:`SnilsRecognizer` — СНИЛС (11 цифр с control-digit алгоритмом);
* :class:`PassportRuRecognizer` — паспорт РФ (серия 4 + номер 6 + context);
* :class:`CreditCaseRecognizer` — номер кредитного дела/договора (regex + context).

Импортируются лениво из
:func:`services.ai.pii.presidio_analyzer.PresidioSanitizerAdapter._build_custom_recognizers`
после успешного init Presidio. Прямой импорт без установленного `presidio_analyzer`
приведёт к ImportError — это by design (только активный PII layer использует их).
"""

from __future__ import annotations

from src.backend.services.ai.pii.recognizers.credit_case_recognizer import (
    CreditCaseRecognizer,
)
from src.backend.services.ai.pii.recognizers.inn_recognizer import InnRecognizer
from src.backend.services.ai.pii.recognizers.passport_ru_recognizer import (
    PassportRuRecognizer,
)
from src.backend.services.ai.pii.recognizers.snils_recognizer import SnilsRecognizer

__all__ = (
    "CreditCaseRecognizer",
    "InnRecognizer",
    "PassportRuRecognizer",
    "SnilsRecognizer",
)
