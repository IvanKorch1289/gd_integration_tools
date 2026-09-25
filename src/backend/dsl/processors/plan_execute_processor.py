"""plan_execute_processor переехал в :mod:`dsl.engine.processors.plan_execute_processor`.

W2 P0-3 Phase 1B (cycle 152, MINIMAX plan): canonical-реализация теперь живёт в
``src.backend.dsl.engine.processors.plan_execute_processor``. Этот модуль — re-export shim
для backward-compat с использованием ``__getattr__`` lazy import
(проксирует любые классы/data-классы/enum'ы из canonical).

Migration::

    # До:
    from src.backend.dsl.processors.plan_execute_processor import *

    # После (canonical):
    from src.backend.dsl.engine.processors.plan_execute_processor import *

DEPRECATED (MINIMAX W2 P0-3, cycle 152): импорт из
``src.backend.dsl.processors.plan_execute_processor`` emits ``DeprecationWarning``.
Removal запланирован на cycle 156 (после telemetry audit).

См. ADR-0313, ADR-0314.
"""

from __future__ import annotations

import importlib as _importlib
import warnings as _warnings
from types import ModuleType
from typing import Any as _Any

_warnings.warn(
    "src.backend.dsl.processors.plan_execute_processor is deprecated; "
    "import from src.backend.dsl.engine.processors.plan_execute_processor instead. "
    "See ADR-0313/0314 (W2 P0-3 processor consolidation). Removal planned: cycle 156.",
    DeprecationWarning,
    stacklevel=2,
)

_CANONICAL_MODULE = "src.backend.dsl.engine.processors.plan_execute_processor"
_canonical: ModuleType | None = None  # lazy


def __getattr__(name: str) -> _Any:
    """Lazy proxy: import canonical module + return requested attribute.

    Преимущество перед ``from canonical import *``: импортируем только когда
    действительно нужен attribute, что ускоряет cold-start (особенно если
    импорт через legacy — это warning, который tooling может подавить).
    """
    global _canonical
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return getattr(_canonical, name)


def __dir__() -> list[str]:
    """``dir()`` через canonical module для tab-completion и introspection."""
    global _canonical
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return dir(_canonical)
