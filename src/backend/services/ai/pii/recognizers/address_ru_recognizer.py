"""Recognizer российских адресов с context-бустингом (S28 W5, S218 refactor).

Russian address patterns detected via regex + contextual signals:

* г. / гор. / город — city name
* ул. / улица / пер. / переулок — street
* д. / дом — house number
* кв. / квартира / офис — apartment/office
* индекс — 6-digit postal code

Context boost words: "проживаю", "зарегистрирован", "адрес", "по адресу",
"место жительства", "фактический адрес", "юридический адрес".

Address detection is inherently imprecise without NER. Score is moderate (0.5)
to allow context to influence the final verdict.

S218: refactored на базе :class:`RegexPiiRecognizer`.
"""

from __future__ import annotations

from presidio_analyzer import Pattern

from src.backend.services.ai.pii.recognizers._base import RegexPiiRecognizer

__all__ = ("AddressRuRecognizer",)


class AddressRuRecognizer(RegexPiiRecognizer):
    """Presidio recognizer для российских адресов.

    Регистрирует entity type ``ADDRESS_RU``. Средний score (0.5) —
    contextual words могут повысить до 0.8.

    Не пытается валидировать адрес (это NER-задача, не regex). Цель —
    перехватить типичные форматы прежде чем они попадут в LLM.
    """

    # Patterns for common Russian address components
    # Combined into a single regex that matches multi-part addresses
    ADDRESS_PATTERN = (
        r"\b(?:(?:г\.?|город|гор)\s+[А-ЯЁ][а-яё]+(?:[-\s][А-ЯЁ][а-яё]+)*)?"
        r"(?:(?:[уул]\.?\s+(?:(?:[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?)|(?:[а-яё]+[-\s][А-ЯЁ][а-яё]+))(?:\s+(?:пер|улица|переулок|пр-кт| проспект))?)?)"
        r"(?:(?:д\.?|дом)\s*\d+[а-яёА-ЯЁ]?(?:\s*,\s*(?:к\.?|корпус|стр|строение)\s*\d+)?)?"
        r"(?:(?:кв\.?|квартира|офис)\s*\d+)?"
        r"(?:(?:\s*,?\s*\d{6})?)"
    )

    SHORT_ADDRESS_PATTERN = (
        r"\b[А-ЯЁ][а-яё]+\s+[А-ЯЁ][а-яё]+(?:\s*[А-ЯЁ][а-яё]+)*"
        r"(?:[\s,]+(?:ул\.?|пер\.?|пр\.?|пр-кт|д\.?|кв\.?)\s*[^\s,]+)*"
    )

    POSTAL_CODE_PATTERN = r"\b\d{6}\b"

    SUPPORTED_ENTITY = "ADDRESS_RU"
    PATTERNS = [
        Pattern(name="ru_address_full", regex=ADDRESS_PATTERN, score=0.5),
        Pattern(name="ru_address_short", regex=SHORT_ADDRESS_PATTERN, score=0.4),
        Pattern(name="ru_postal_code", regex=POSTAL_CODE_PATTERN, score=0.3),
    ]
    CONTEXT = [
        "проживаю",
        "зарегистрирован",
        "зарегистрирована",
        "адрес",
        "по адресу",
        "место жительства",
        "фактический адрес",
        "юридический адрес",
        "почтовый адрес",
        "адрес регистрации",
        "адрес проживания",
        "выслать по адресу",
        "доставка по адресу",
        "отправка по адресу",
    ]