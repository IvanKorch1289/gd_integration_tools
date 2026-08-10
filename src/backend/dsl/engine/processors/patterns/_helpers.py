"""S175 Phase 3: _SafeDict helper — restored from original patterns.py.

Parallel WIP создал patterns/ subpackage (Phase 2), но забыл добавить
``_SafeDict`` helper (функция используется в formatter.py для
format_map с missing-key fallback).
"""

from __future__ import annotations


class _SafeDict(dict):
    """Dict that returns ``"{{key}}"`` для missing keys в ``str.format_map()``.

    Используется в template formatter'е для graceful handling неопределённых
    variables: вместо ``KeyError`` подставляется literal placeholder.

    Example:
        >>> template = "Hello {name}, age {age}"
        >>> template.format_map(_SafeDict({"name": "Alice"}))
        'Hello Alice, age {age}'

    """

    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"
