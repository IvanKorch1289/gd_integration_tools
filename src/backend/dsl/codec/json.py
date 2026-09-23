"""Backward-compat shim — re-exports из :mod:`core.codec.json` (Cycle 31 P1).

Содержимое было перемещено в ``core/codec/json.py`` для устранения 13
layer-violation (infrastructure модули импортировали эту утилиту из dsl/).
Этот файл оставлен как re-export shim для backward compatibility.

Новые потребители должны импортировать из:
    ``from src.backend.core.codec.json import json_dumps, json_loads``

Историческая документация ниже — оригинальный docstring модуля.

---

Shared JSON utilities for DSL pipelines (Wave 7.4, S29 W2).

Оборачивает :mod:`orjson` с поддержкой Pydantic-типов, dataclasses, UUID,
datetime, Decimal, Enum, bytes. Используется в sinks/sources, observability,
workflow (HMAC chains), и DSL routing.

Архитектурно: чистая утилита без DSL-логики → перенесена в ``core/codec/``.
"""

from __future__ import annotations

# Re-export everything from the canonical location. This is a back-compat
# shim — all new code should import from src.backend.core.codec.json directly.
from src.backend.core.codec.json import (
    TYPE_MARKER,
    VALUE_MARKER,
    canonical_json_bytes,
    dumps_bytes,
    dumps_str,
    from_jsonable,
    json_dumps,
    json_loads,
    loads,
    to_jsonable,
)

__all__ = (
    "TYPE_MARKER",
    "VALUE_MARKER",
    "canonical_json_bytes",
    "dumps_bytes",
    "dumps_str",
    "from_jsonable",
    "json_dumps",
    "json_loads",
    "loads",
    "to_jsonable",
)
