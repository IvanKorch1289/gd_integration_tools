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
from src.backend.dsl.engine.processors.proxy.headers import HeaderMapPolicy
from src.backend.dsl.engine.processors.proxy.redirect import RedirectProcessor

__all__ = (
    "ExposeProxyProcessor",
    "ForwardToProcessor",
    "HeaderMapPolicy",
    "ProxyInboundSpec",
    "ProxyOutboundSpec",
    "RedirectProcessor",
)
