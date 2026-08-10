"""Proxy pass-through и redirect процессоры (Wave 3.5-3.6 / ADR-014).

Публичный re-export:

    from src.backend.dsl.engine.processors.proxy import (
        ExposeProxyProcessor,
        ForwardToProcessor,
        HeaderMapPolicy,
        RedirectProcessor,
    )
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.proxy.expose import (
    ExposeProxyProcessor,
    ProxyInboundSpec,
)
from src.backend.dsl.engine.processors.proxy.forward import (
    ForwardToProcessor,
    ProxyOutboundSpec,
)
from src.backend.dsl.engine.processors.proxy.headers import HeaderMapPolicy  # noqa: F401 — re-export
from src.backend.dsl.engine.processors.proxy.redirect import RedirectProcessor  # noqa: F401 — re-export

__all__ = (
    "ExposeProxyProcessor",
    "ForwardToProcessor",
    "HeaderMapPolicy",
    "ProxyInboundSpec",
    "ProxyOutboundSpec",
    "RedirectProcessor",
)
