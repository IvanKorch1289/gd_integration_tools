"""DEPRECATED — thin re-export to ``core/resilience/retry.py`` (A3_RETRY).

Все реализации (``make_async_retry``, ``async_retry``, ``_log_before_sleep``)
перенесены в canonical-модуль :mod:`src.backend.core.resilience.retry`.

Этот файл сохранён для backward-compat существующих импортов (~11 callsites).
Новый код должен импортировать напрямую из canonical.

Миграция::

    # было
    from src.backend.infrastructure.resilience.retry import make_async_retry
    # стало
    from src.backend.core.resilience.retry import make_async_retry

Coexistence with ``core/resilience/retry.py``: tenacity wrapper consolidated.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "infrastructure.resilience.retry is deprecated; "
    "use src.backend.core.resilience.retry instead",
    DeprecationWarning,
    stacklevel=2,
)

from src.backend.core.resilience.retry import (  # noqa: E402,F401
    _log_before_sleep,
    async_retry,
    make_async_retry,
)

__all__ = ("async_retry", "make_async_retry")
