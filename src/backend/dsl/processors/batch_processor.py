"""Backward-compat shim — BatchProcessor переехал в :mod:`dsl.engine.processors`.

W2 P0-3 (cycle 152, MINIMAX plan): canonical-реализация теперь живёт в
``src.backend.dsl.engine.processors.batch_processor``. Этот модуль —
re-export shim для backward-compat с использованием ``__getattr__``
lazy import (проксирует любые классы из canonical).

Migration::

    # До:
    from src.backend.dsl.processors.batch_processor import *

    # После (canonical):
    from src.backend.dsl.engine.processors.batch_processor import *

DEPRECATED (MINIMAX W2 P0-3, cycle 152): импорт из
``src.backend.dsl.processors.batch_processor`` emits ``DeprecationWarning``.
Removal запланирован на cycle 156 (после telemetry audit).

См. ADR-0313 (Phase 1A pilot), ADR-0314 (Phase 1B — все 6 single-file).
"""

from __future__ import annotations

import importlib as _importlib
import warnings as _warnings
from types import ModuleType
from typing import Any as _Any

_warnings.warn(
    "src.backend.dsl.processors.batch_processor is deprecated; "
    "import from src.backend.dsl.engine.processors.batch_processor instead. "
    "See ADR-0313/0314 (W2 P0-3 processor consolidation). Removal planned: cycle 156.",
    DeprecationWarning,
    stacklevel=2,
)

_CANONICAL_MODULE = "src.backend.dsl.engine.processors.batch_processor"
_canonical: ModuleType | None = None  # lazy


def __getattr__(name: str) -> _Any:
    """Lazy proxy: import canonical module + return requested attribute."""
    global _canonical
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return getattr(_canonical, name)


def __dir__() -> list[str]:
    """``dir()`` через canonical module для tab-completion и introspection."""
    module = (
        _canonical
        if _canonical is not None
        else _importlib.import_module(_CANONICAL_MODULE)
    )
    return dir(module)  # делегирование: тот же lazy-import путь
