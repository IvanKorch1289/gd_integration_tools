"""DEPRECATED: re-export shim (S168 W15 P2-10).

Users filter schemas moved to
src.backend.extensions.core_entities.users.schemas.filter per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings

from extensions.core_entities.users.schemas import filter as _filter_module  # noqa: E402,F401

__all__ = getattr(_filter_module, "__all__", ())

warnings.warn(
    "src.backend.schemas.filter_schemas.users is deprecated "
    "(S168 W15 P2-10), use "
    "extensions.core_entities.users.schemas.filter instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)
