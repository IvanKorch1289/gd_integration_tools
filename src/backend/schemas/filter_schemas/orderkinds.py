"""DEPRECATED: re-export shim (S168 W15 P2-10).

Orderkinds filter schemas moved to
src.backend.extensions.core_entities.orderkinds.schemas.filter per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings

from extensions.core_entities.orderkinds.schemas import filter as _filter_module  # noqa: E402,F401

__all__ = getattr(_filter_module, "__all__", ())

warnings.warn(
    "src.backend.schemas.filter_schemas.orderkinds is deprecated "
    "(S168 W15 P2-10), use "
    "extensions.core_entities.orderkinds.schemas.filter instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)
