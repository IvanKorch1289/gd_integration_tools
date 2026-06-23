"""DEPRECATED: re-export shim (S168 W14 P2-10).

Order model moved to
src.backend.extensions.core_entities.orders.domain.models per
master prompt v8 P2-10. Will be removed в S169+.
"""

import warnings

from extensions.core_entities.orders.domain.models import Order  # noqa: E402,F401

warnings.warn(
    "src.backend.core.domain.models.orders is deprecated "
    "(S168 W14 P2-10), use "
    "extensions.core_entities.orders.domain.models instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("Order",)
