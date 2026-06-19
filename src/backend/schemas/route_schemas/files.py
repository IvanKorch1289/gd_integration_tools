"""DEPRECATED: re-export shim (S168 W15 P2-10).

File route schemas moved to
src.backend.extensions.core_entities.files.schemas.route per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings

from extensions.core_entities.files.schemas import route as _route_module  # noqa: E402,F401

# Re-export all public symbols from new location
__all__ = getattr(_route_module, "__all__", ())

warnings.warn(
    "src.backend.schemas.route_schemas.files is deprecated "
    "(S168 W15 P2-10), use "
    "extensions.core_entities.files.schemas.route instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)
