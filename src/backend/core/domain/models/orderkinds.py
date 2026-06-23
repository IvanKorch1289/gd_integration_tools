"""DEPRECATED: re-export shim (S168 W13 P2-10).

OrderKind model moved to
src.backend.extensions.core_entities.orderkinds.domain.models per
master prompt v8 P2-10. Will be removed в S169+.
"""

import warnings

from extensions.core_entities.orderkinds.domain.models import (  # noqa: E402,F401
    OrderKind,
)

warnings.warn(
    "src.backend.core.domain.models.orderkinds is deprecated "
    "(S168 W13 P2-10), use "
    "extensions.core_entities.orderkinds.domain.models instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("OrderKind",)
