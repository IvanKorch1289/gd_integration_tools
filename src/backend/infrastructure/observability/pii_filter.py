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

from typing import Any

__all__ = ("mask_pii", "redact_for_observability")

# S222: Email/Phone/Card shared via core.security.pii_patterns.
# S219: SNILS/INN/RU_PASSPORT (single source of truth).
from src.backend.core.security.pii_patterns import (  # noqa: F401
    CARD as _CARD,
    EMAIL as _EMAIL,
    INN as _INN,
    PHONE as _PHONE,
    RU_PASSPORT as _RU_PASSPORT,
    SNILS as _SNILS,
)


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
