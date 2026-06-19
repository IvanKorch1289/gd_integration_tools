"""DEPRECATED: re-export shim (S168 W15 P2-10).

OrderKind route schemas moved to
src.backend.extensions.core_entities.orderkinds.schemas.route per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings

from extensions.core_entities.orderkinds.schemas import route as _route_module  # noqa: E402,F401

__all__ = getattr(_route_module, "__all__", ())

warnings.warn(
    "src.backend.schemas.route_schemas.orderkinds is deprecated "
    "(S168 W15 P2-10), use "
    "extensions.core_entities.orderkinds.schemas.route instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)
