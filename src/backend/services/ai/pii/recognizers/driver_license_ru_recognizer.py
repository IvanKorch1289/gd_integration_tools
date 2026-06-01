"""Recognizer водительских удостоверений РФ (S28 W5).

Russian driver license format (национальные права):

* Старый формат: серия (2 буквы + 6 цифр, напр. "АА 123456")
* Новый формат (с 2014): 2 буквы + 6 цифр (напр. "AA1234567" или "AA 1234567")
* Поле "КEMP" — не относится к номеру водительского удостоверения

Источник: Приказ МВД России от 13.05.2009 № 365 + изменения 2014.

Context boost: "водительское удостоверение", "права", "номер удостоверения",
"выдан", "водительские права", "категория прав", "ВУ".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from presidio_analyzer import Pattern, PatternRecognizer

if TYPE_CHECKING:
    pass

__all__ = ("DriverLicenseRuRecognizer",)


class DriverLicenseRuRecognizer(PatternRecognizer):
    """Presidio recognizer для российских водительских удостоверений.

    Регистрирует entity type ``DRIVER_LICENSE_RU``.
    Поддерживает старый (с пробелом) и новый (без пробела) форматы.
    """

    # New format (2014+): 2 CYRILLIC letters + 6 digits (can have space)
    # Example: АА1234567, АА 123456, ММ7654321
    NEW_FORMAT_PATTERN = r"\b[А-ЯЁA-Z]{2}\s?\d{6}\b"

    # Old format: 2 CYRILLIC letters + 6 digits (always with space)
    # Example: "АА 123456", "ММ 765432"
    OLD_FORMAT_PATTERN = r"\b[А-ЯЁ]{2}\s\d{6}\b"

    # Alternative: UK-style (for international licenses) — Latin letters
    # Example: "AA1234567"
    LATIN_FORMAT_PATTERN = r"\b[A-Z]{2}\s?\d{6}\b"

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="ru_driver_license_new",
                regex=DriverLicenseRuRecognizer.NEW_FORMAT_PATTERN,
                score=0.8,
            ),
            Pattern(
                name="ru_driver_license_old",
                regex=DriverLicenseRuRecognizer.OLD_FORMAT_PATTERN,
                score=0.85,
            ),
            Pattern(
                name="ru_driver_license_latin",
                regex=DriverLicenseRuRecognizer.LATIN_FORMAT_PATTERN,
                score=0.6,
            ),
        ]
        super().__init__(
            supported_entity="DRIVER_LICENSE_RU",
            supported_language="ru",
            patterns=patterns,
            context=[
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
            ],
        )
