"""S68 W3 sample refactor: local ``dumps_str`` для audit infrastructure.

TD-S65-W4 violations: 2 entries для ``infrastructure/audit/ →
src.backend.dsl.codec.json:dumps_str``:
- ``src/backend/infrastructure/audit/event_log.py:78``
- ``src/backend/infrastructure/audit/jsonl_audit.py:20``

infrastructure/audit reverse-зависит от dsl (meta-layer) — это
architecture smell. ``dumps_str`` — trivial function (orjson.dumps +
UTF-8 decode, 2 строки). Trivially moveable в local helper.

После S68 W3: audit имеет свой local JSON codec, ZERO зависимости от
dsl. dsl.codec.json сохраняет свой ``dumps_str`` для workflow use-cases
(unrelated to audit).

Примечание: S68 W2 + S68 W3 вместе закрыли 4 violations (RetryPolicy +
audit JSON). Allowlist: 201 → 199 → 197.
"""

from __future__ import annotations

from typing import Any

# S68 W3: локальный orjson-based JSON serializer для audit infrastructure.
# Избегает reverse-dependency на dsl/codec/json (TD-S65-W4).
# Использует те же defaults что и dsl/codec/dumps_str: sort_keys/indent
# опциональны, default=str для non-serializable values.
try:
    import orjson

    def dumps_str(
        value: Any, *, sort_keys: bool = False, indent: bool = False
    ) -> str:
        """Локальный orjson-based JSON сериализатор (UTF-8 str).

        S68 W3: replaces infrastructure/audit/ reverse import
        на dsl/codec/json. Mirror API dsl.codec.dumps_str для
        compatibility (same kwargs, same default=str fallback).
        """
        options: int = 0
        if sort_keys:
            options |= orjson.OPT_SORT_KEYS
        if indent:
            options |= orjson.OPT_INDENT_2
        return orjson.dumps(value, option=options, default=str).decode("utf-8")

except ImportError:
    # Fallback для environments без orjson (dev-light, tests).
    import json

    def dumps_str(
        value: Any, *, sort_keys: bool = False, indent: bool = False
    ) -> str:
        """Fallback stdlib JSON сериализатор (если orjson недоступен)."""
        kwargs: dict[str, Any] = {"default": str}
        if sort_keys:
            kwargs["sort_keys"] = True
        if indent:
            kwargs["indent"] = 2
        return json.dumps(value, **kwargs)


__all__ = ("dumps_str",)
