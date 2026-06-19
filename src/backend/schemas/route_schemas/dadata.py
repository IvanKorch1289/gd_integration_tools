"""DEPRECATED: re-export shim (S168 W17 P2-10).

DaData route schemas moved to
src.backend.extensions.dadata.schemas.route per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings

from extensions.dadata.schemas import route as _route_module  # noqa: E402,F401

__all__ = getattr(_route_module, "__all__", ())

warnings.warn(
    "src.backend.schemas.route_schemas.dadata is deprecated "
    "(S168 W17 P2-10), use "
    "extensions.dadata.schemas.route instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)
