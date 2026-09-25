"""Backward-compat shim — event_store subpackage переехал в :mod:`dsl.engine.processors.event_store`.

W2 P0-3 Phase 1C (cycle 152, MINIMAX plan): canonical-реализация теперь живёт в
``src.backend.dsl.engine.processors.event_store``. Этот модуль — re-export shim
для backward-compat с использованием ``__getattr__`` lazy proxy pattern
(проксирует любые классы/data-классы/функции из canonical subpackage).

Migration::

    # До:
    from src.backend.dsl.processors.event_store import *

    # После (canonical):
    from src.backend.dsl.engine.processors.event_store import *

DEPRECATED (MINIMAX W2 P0-3, cycle 152): импорт из
``src.backend.dsl.processors.event_store`` emits ``DeprecationWarning``.
Removal запланирован на cycle 156 (после telemetry audit).

См. ADR-0313, ADR-0314, ADR-0315.
"""

from __future__ import annotations

import importlib as _importlib
import warnings as _warnings
from types import ModuleType
from typing import Any as _Any

_warnings.warn(
    "src.backend.dsl.processors.event_store is deprecated; "
    "import from src.backend.dsl.engine.processors.event_store instead. "
    "See ADR-0313/0314/0315 (W2 P0-3 processor consolidation). Removal planned: cycle 156.",
    DeprecationWarning,
    stacklevel=2,
)

_CANONICAL_MODULE = "src.backend.dsl.engine.processors.event_store"
_canonical: ModuleType | None = None  # lazy


def __getattr__(name: str) -> _Any:
    """Lazy proxy: import canonical subpackage + return requested attribute."""
    global _canonical
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return getattr(_canonical, name)


def __dir__() -> list[str]:
    """``dir()`` через canonical subpackage для tab-completion."""
    global _canonical
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return dir(_canonical)
