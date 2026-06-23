"""DEPRECATED: re-export shim (S168 W14 P2-10).

OrderAdmin moved to
src.backend.extensions.core_entities.orders.admin per
master prompt v8 P2-10. Will be removed в S169+.
"""

import warnings

from extensions.core_entities.orders.admin import OrderAdmin  # noqa: E402,F401

warnings.warn(
    "src.backend.utilities.admin_panel.orders is deprecated "
    "(S168 W14 P2-10), use "
    "extensions.core_entities.orders.admin instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("OrderAdmin",)
