"""S107 W1 — shim: ``infrastructure.database.migrations._compat`` → ``core.database.dialect_types``.

DEPRECATED (S107 W1, TD-002 residual): canonical path —
:mod:`src.backend.core.database.dialect_types`. Этот shim остаётся
для backward compat с extensions / pre-S107 кодом; new code ДОЛЖЕН
использовать canonical import:

    # canonical (S107+):
    from src.backend.core.database.dialect_types import json_b, uuid_t

    # legacy (deprecated, will be removed в S109+):
    from src.backend.infrastructure.database.migrations._compat import json_b  # noqa: DEPRECATED
"""

from __future__ import annotations

import warnings

from src.backend.core.database.dialect_types import (  # noqa: F401  re-export
    json_b,
    uuid_t,
)

__all__ = ("json_b", "uuid_t")

warnings.warn(
    "src.backend.infrastructure.database.migrations._compat is deprecated; "
    "use src.backend.core.database.dialect_types (S107 W1, TD-002).",
    DeprecationWarning,
    stacklevel=2,
)
