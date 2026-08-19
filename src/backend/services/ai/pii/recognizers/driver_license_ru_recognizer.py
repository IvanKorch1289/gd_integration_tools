"""Recognizer водительских удостоверений РФ (S28 W5, S218 refactor).

Russian driver license format (национальные права):

* Старый формат: серия (2 буквы + 6 цифр, напр. "АА 123456")
* Новый формат (с 2014): 2 буквы + 6 цифр (напр. "AA1234567" или "AA 1234567")
* Поле "КEMP" — не относится к номеру водительского удостоверения

Источник: Приказ МВД России от 13.05.2009 № 365 + изменения 2014.

Context boost: "водительское удостоверение", "права", "номер удостоверения",
"выдан", "водительские права", "категория прав", "ВУ".

S218: refactored на базе :class:`RegexPiiRecognizer`.
"""

from __future__ import annotations

from presidio_analyzer import Pattern

from src.backend.services.ai.pii.recognizers._base import RegexPiiRecognizer

__all__ = ("DriverLicenseRuRecognizer",)


class DriverLicenseRuRecognizer(RegexPiiRecognizer):
    """Presidio recognizer для российских водительских удостоверений.

    Регистрирует entity type ``DRIVER_LICENSE_RU``.
    Поддерживает старый (с пробелом) и новый (без пробела) форматы.
    """

    NEW_FORMAT_PATTERN = r"\b[А-ЯЁA-Z]{2}\s?\d{6}\b"
    OLD_FORMAT_PATTERN = r"\b[А-ЯЁ]{2}\s\d{6}\b"
    LATIN_FORMAT_PATTERN = r"\b[A-Z]{2}\s?\d{6}\b"

    SUPPORTED_ENTITY = "DRIVER_LICENSE_RU"
    PATTERNS = [
        Pattern(name="ru_driver_license_new", regex=NEW_FORMAT_PATTERN, score=0.8),
        Pattern(name="ru_driver_license_old", regex=OLD_FORMAT_PATTERN, score=0.85),
        Pattern(name="ru_driver_license_latin", regex=LATIN_FORMAT_PATTERN, score=0.6),
    ]
    CONTEXT = [
        "водительское удостоверение",
        "водительские права",
        "права",
        "номер удостоверения",
        "выдан",
        "категория прав",
        "ВУ",
        "удостоверение водителя",
        "водительских прав",
        "номер водительского",
        "получил права",
        "заменить права",
    ]
