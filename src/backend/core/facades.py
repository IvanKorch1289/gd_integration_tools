"""Sprint 11 P1-18: backward-compat shim → ``core.api`` (canonical facade).

Per docs/PROJECT_PLAN.md V22-2 (D102, D187), 16/17 capability-checked
facades были в ``core/facades.py``. После cycle 29 (Master Prompt P1-#1)
facade переехал в ``core/api/__init__.py`` (canonical location per
boundary rule: extensions import ТОЛЬКО ``src.backend.sdk`` +
``src.backend.core.api``).

Этот shim — backward-compat alias для:
* Doc references в 7+ docs (PROJECT_PLAN.md, PROJECT_RECOMMENDATIONS.md,
  PROJECT_FINAL_SUMMARY.md, etc.) — `core/facades.py` все еще упоминается.
* Любой external tooling, который импортирует ``src.backend.core.facades``.

Ponytail: minimum shim (4 LOC). Re-exports everything from canonical
``core.api``. Lazy ``__getattr__`` preserved (через wildcard + explicit
``__all__``/``__getattr__`` imports).

DEPRECATED (MINIMAX W3 P0-4, cycle 152): import этого модуля эмитит
``DeprecationWarning`` при загрузке. Removal запланирован на релиз
после audit импортёров (target: cycle 156 / 1 релиз после telemetry).
Для нового кода: ``from src.backend.core.api import X``.

References:
- ADR-0249 (capability-checked facades)
- ADR-0307 (W3 P0-4 shim inventory + classification)
- ``docs/PROJECT_PLAN.md`` V22-2 / V22-10
- ``docs/PROJECT_RECOMMENDATIONS.md`` D102
- ``docs/_build/.../PROJECT_FINAL_SUMMARY.md`` "D102/D187 (capability-checked facades)"
"""

from __future__ import annotations

import warnings as _warnings

# Emit DeprecationWarning on import — encourages migration to core.api.
# stacklevel=2 указывает на caller import site.
_warnings.warn(
    "src.backend.core.facades is deprecated; use src.backend.core.api instead. "
    "See ADR-0307 (W3 P0-4 shim cleanup). Removal planned: cycle 156.",
    DeprecationWarning,
    stacklevel=2,
)

from src.backend.core.api import *  # noqa: F401,F403 — backward-compat re-export
from src.backend.core.api import (  # noqa: F401 — lazy attrs
    __all__,
    __dir__,
    __getattr__,
)

__all__ = __all__  # re-export __all__ from core.api
