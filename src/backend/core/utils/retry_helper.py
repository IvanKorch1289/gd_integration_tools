"""DEPRECATED — thin re-export to ``core/resilience/retry.py`` (A3_RETRY).

Все реализации перенесены в canonical-модуль
:mod:`src.backend.core.resilience.retry`.

Этот файл сохранён исключительно для backward-compat существующих импортов
(~11 callsites). Новый код должен импортировать напрямую из canonical.

Миграция::

    # было
    from src.backend.core.utils.retry_helper import retry_async, default_retryable
    # стало
    from src.backend.core.resilience.retry import retry_async, default_retryable
"""

from __future__ import annotations

import warnings

warnings.warn(
    "core.utils.retry_helper is deprecated; "
    "use src.backend.core.resilience.retry instead",
    DeprecationWarning,
    stacklevel=2,
)

from src.backend.core.resilience.retry import (  # noqa: E402,F401
    default_retryable,
    retry_async,
)

__all__ = ("retry_async", "default_retryable")
