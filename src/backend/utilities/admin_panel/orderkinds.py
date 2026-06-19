"""DEPRECATED: re-export shim (S168 W14 P2-10).

OrderKindAdmin moved to
src.backend.extensions.core_entities.orderkinds.admin per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings
from extensions.core_entities.orderkinds.admin import (  # noqa: E402,F401
    OrderKindAdmin,
)

warnings.warn(
    "src.backend.utilities.admin_panel.orderkinds is deprecated "
    "(S168 W14 P2-10), use "
    "extensions.core_entities.orderkinds.admin instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("OrderKindAdmin",)
