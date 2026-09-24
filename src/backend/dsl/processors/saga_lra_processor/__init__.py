"""Backward-compat shim — saga_lra_processor subpackage переехал в :mod:`dsl.engine.processors.saga_lra_processor`.

W2 P0-3 Phase 2 (cycle 152, MINIMAX plan): canonical-реализация теперь живёт в
``src.backend.dsl.engine.processors.saga_lra_processor``. Этот модуль —
re-export shim для backward-compat.

W2 P0-3 Phase 2 Decision: SagaLRA — **другая реализация** (mixin-based,
state machine с 5 states + SagaCompensationError/SagaLRAError exceptions),
не дубликат current saga_lra.py (single-file, simpler state). ADR-0316
содержит decision matrix: Variant A (migrate legacy subpackage в
engine.processors) принят как канонический для legacy API.

Migration::

    # До:
    from src.backend.dsl.processors.saga_lra_processor import SagaLRAProcessor

    # После (canonical):
    from src.backend.dsl.engine.processors.saga_lra_processor import SagaLRAProcessor

DEPRECATED (MINIMAX W2 P0-3, cycle 152): импорт из
``src.backend.dsl.processors.saga_lra_processor`` emits ``DeprecationWarning``.
Removal запланирован на cycle 156 (с после telemetry audit).

См. ADR-0316.
"""

from __future__ import annotations

import importlib as _importlib
import warnings as _warnings
from typing import Any as _Any

_warnings.warn(
    "src.backend.dsl.processors.saga_lra_processor is deprecated; "
    "import from src.backend.dsl.engine.processors.saga_lra_processor instead. "
    "See ADR-0316 (W2 P0-3 SagaLRA Phase 2). Removal planned: cycle 156.",
    DeprecationWarning,
    stacklevel=2,
)

_CANONICAL_MODULE = "src.backend.dsl.engine.processors.saga_lra_processor"
_canonical = None


def __getattr__(name: str) -> _Any:
    """Lazy proxy: import canonical subpackage + return requested attribute."""
    global _canonical
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return getattr(_canonical, name)


def __dir__() -> list[str]:
    """``dir()`` через canonical subpackage для tab-completion."""
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return dir(_canonical)
