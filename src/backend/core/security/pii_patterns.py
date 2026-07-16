"""Shared PII regex patterns (S219).

Single source of truth для patterns, которые используются в нескольких
модулях (например, ``core/security/pii_masker.py`` для DSL/audit masking
и ``infrastructure/observability/pii_filter.py`` для structlog masking).

Раньше эти 3 regex были скопированы в оба файла — при изменении формата
(например, добавление нового разделителя в SNILS) легко пропустить одно
из мест. S219 консолидирует в один модуль.

Note: patterns могут быть вынесены в YAML config в будущем (для hot-reload),
сейчас — hardcoded compiled regex (Python compile-once).
"""

from __future__ import annotations

import re

__all__ = (
    "RU_PASSPORT",
    "INN",
    "SNILS",
)


# RU SNILS — ``XXX-XXX-XXX YY`` (с пробелом или без перед последними двумя).
SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b")

# INN — 10 (юр.лицо) или 12 (физ.лицо) цифр сплошняком (разделители
# пробелами означают, что это уже не INN, а phone/passport).
INN = re.compile(r"\b\d{12}\b|\b\d{10}\b")

# RU passport — 4 цифры + пробел + 6 цифр (стандартный формат серия+номер).
# Без пробела 10 цифр — это INN, не passport.
RU_PASSPORT = re.compile(r"\b\d{4}\s\d{6}\b")