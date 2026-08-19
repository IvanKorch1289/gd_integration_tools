"""Shared PII regex patterns (S219, S221).

Single source of truth для patterns, которые используются в нескольких
модулях (например, ``core/security/pii_masker.py`` для DSL/audit masking
и ``infrastructure/observability/pii_filter.py`` для structlog masking).

Раньше эти regex были скопированы в оба файла — при изменении формата
(например, добавление нового разделителя в SNILS) легко пропустить одно
из мест. S219 консолидирует SNILS/INN/RU_PASSPORT, S221 — EMAIL/PHONE.

Note: patterns могут быть вынесены в YAML config в будущем (для hot-reload),
сейчас — hardcoded compiled regex (Python compile-once).
"""

from __future__ import annotations

import re

__all__ = ("CARD", "EMAIL", "INN", "PHONE", "RU_PASSPORT", "SNILS")


# RU SNILS — ``XXX-XXX-XXX YY`` (с пробелом или без перед последними двумя).
SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b")

# INN — 10 (юр.лицо) или 12 (физ.лицо) цифр сплошняком (разделители
# пробелами означают, что это уже не INN, а phone/passport).
INN = re.compile(r"\b\d{12}\b|\b\d{10}\b")

# RU passport — 4 цифры + пробел + 6 цифр (стандартный формат серия+номер).
# Без пробела 10 цифр — это INN, не passport.
RU_PASSPORT = re.compile(r"\b\d{4}\s\d{6}\b")

# S221: Email (RFC 5321-совместимое упрощение).
# Shared between pii_masker и pii_filter (были скопированы с разным escape order).
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# S221: Phone — E.164 (+7...) или RU-формат с пробелами/скобками/дефисами.
# Якорь \+ или непрерывная цифровая последовательность ≥ 10.
PHONE = re.compile(r"\+?\d[\d\s()\-]{8,}\d")

# S222: Credit card — 13–19 цифр (flexible separators).
# Shared between pii_masker и pii_filter (были скопированы с разным escape).
# ai_sanitizer имеет STRICT 4-4-4-4 regex — намеренно другой semantic,
# оставлен локальным.
CARD = re.compile(r"\b(?:\d[ \-]?){13,19}\b")
