"""DEPRECATED: re-export shim (S168 W17 P2-10).

SKB route schemas moved to
src.backend.extensions.skb.schemas.route per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings

from extensions.skb.schemas import route as _route_module  # noqa: E402,F401

__all__ = getattr(_route_module, "__all__", ())

warnings.warn(
    "src.backend.schemas.route_schemas.skb is deprecated "
    "(S168 W17 P2-10), use "
    "extensions.skb.schemas.route instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)
