"""PII redaction filter для logs/spans/metrics (V15 S1, W21).

Применяется ко всем исходящим в observability-бэкенд потокам:

* structlog-processor (см. ``logging/structlog_backend.py``);
* OTEL span attributes;
* Prometheus labels;
* Sentry ``before_send`` (см. ``sentry_init.py``).

Покрытие PII (минимально — 5 типов из S1 DoD):

* email — ``user@host.tld``;
* phone — E.164 / RU-формат с пробелами и скобками;
* RU passport — ``XXXX XXXXXX`` или ``XXXXXXXXXX``;
* SNILS — ``XXX-XXX-XXX YY`` (RU pension id);
* INN — 10 или 12 цифр (legal/individual);
* (бонус) credit card — 13–19 цифр.

API:

* :func:`redact_for_observability(value)` — рекурсивный обход;
* :func:`mask_pii(event_dict)` — pure функция для structlog-processor
  (signature совместима с structlog: ``(logger, method_name, event_dict)``).
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ("mask_pii", "redact_for_observability")

# Email — RFC 5321-совместимое упрощение.
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
# Phone — E.164 (+7...) или RU-формат (+7 (xxx) xxx-xx-xx).
# Якорь \+ или непрерывная цифровая последовательность ≥ 10 (избегаем
# съедания 10-/12-значных INN в составе текста — INN маскируется раньше).
_PHONE = re.compile(r"\+?\d[\d\s()\-]{8,}\d")
# RU SNILS — XXX-XXX-XXX YY.
_SNILS = re.compile(r"\b\d{3}-\d{3}-\d{3}\s?\d{2}\b")
# INN — 10 (LE) или 12 (individual) цифр сплошняком (разделители
# пробелами означают, что это уже не INN, а phone/passport).
_INN = re.compile(r"\b\d{12}\b|\b\d{10}\b")
# Credit card — 13–19 цифр (groups через пробел/тире).
_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
# RU passport — 4 цифры + пробел + 6 цифр (стандартный формат серия+номер).
# Без пробела 10 цифр — это INN, не passport.
_RU_PASSPORT = re.compile(r"\b\d{4}\s\d{6}\b")


def redact_for_observability(value: Any) -> Any:
    """Рекурсивно заменяет PII-значения на маркеры.

    Принимает dict/list/str, не трогает числовые/bool. Порядок применения
    regex'ов важен — более специфичные паттерны идут первыми, чтобы не
    попасть под общие.
    """
    if isinstance(value, str):
        v = value
        # Specific-first: разделительные форматы до сплошных цифр.
        # SNILS (дефисы) → CARD (13+ цифр) → PASSPORT (4 ws 6) → INN
        # (10/12 сплошных) → EMAIL → PHONE (общая цифровая ловушка).
        v = _SNILS.sub("<snils>", v)
        v = _CARD.sub("<card>", v)
        v = _RU_PASSPORT.sub("<passport>", v)
        v = _INN.sub("<inn>", v)
        v = _EMAIL.sub("<email>", v)
        v = _PHONE.sub("<phone>", v)
        return v
    if isinstance(value, dict):
        return {k: redact_for_observability(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_observability(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_for_observability(v) for v in value)
    return value


def mask_pii(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog-processor: маскирует PII во всём event_dict.

    Сигнатура совпадает со structlog-protocol
    (``(logger, method_name, event_dict)``). Возвращает копию dict с
    маскированными значениями — оригинал не мутируется, чтобы downstream
    backends могли работать с ним параллельно.
    """
    return {key: redact_for_observability(value) for key, value in event_dict.items()}
