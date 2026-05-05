"""PII redaction filter для logs/spans/metrics (G3).

Применяется ко всем исходящим в observability-бэкенд потокам:
structlog-processor, OTEL span attributes, Prometheus labels.
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ("redact_for_observability",)

_EMAIL = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
_PHONE = re.compile(r"\+?\d[\d\s()-]{7,}")
_INN = re.compile(r"\b\d{10,12}\b")
_CARD = re.compile(r"\b\d{13,16}\b")
_RU_PASSPORT = re.compile(r"\b\d{4}\s?\d{6}\b")


def redact_for_observability(value: Any) -> Any:
    """Рекурсивно заменяет PII-значения на маркеры.

    Принимает dict/list/str, не трогает числовые/bool.
    """
    if isinstance(value, str):
        v = value
        v = _EMAIL.sub("<email>", v)
        v = _PHONE.sub("<phone>", v)
        v = _CARD.sub("<card>", v)
        v = _RU_PASSPORT.sub("<passport>", v)
        v = _INN.sub("<inn>", v)
        return v
    if isinstance(value, dict):
        return {k: redact_for_observability(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_observability(v) for v in value]
    return value
