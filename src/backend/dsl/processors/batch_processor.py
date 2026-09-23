"""Backward-compat shim — BatchProcessor переехал в :mod:`dsl.engine.processors`.

W2 P0-3 (cycle 152, MINIMAX plan): canonical-реализация теперь живёт в
``src.backend.dsl.engine.processors.batch_processor``. Этот модуль —
re-export shim для backward-compat.

Migration::

    # До:
    from src.backend.dsl.processors.batch_processor import BatchProcessor

    # После (canonical):
    from src.backend.dsl.engine.processors.batch_processor import BatchProcessor

DEPRECATED (MINIMAX W2 P0-3, cycle 152): импорт из
``src.backend.dsl.processors.batch_processor`` emits ``DeprecationWarning``.
Removal запланирован на cycle 156 (после telemetry audit).

См. ADR-0313.
"""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "src.backend.dsl.processors.batch_processor is deprecated; "
    "import from src.backend.dsl.engine.processors.batch_processor instead. "
    "See ADR-0313 (W2 P0-3 processor consolidation). Removal planned: cycle 156.",
    DeprecationWarning,
    stacklevel=2,
)

from src.backend.dsl.engine.processors.batch_processor import (  # noqa: F401, E402 — re-export
    BatchProcessor,
)

__all__ = ("BatchProcessor",)