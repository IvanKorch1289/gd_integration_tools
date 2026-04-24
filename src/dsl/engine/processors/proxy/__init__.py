"""Proxy pass-through процессоры (Wave 3.5 / ADR-014).

Публичный re-export:

    from app.dsl.engine.processors.proxy import (
        ExposeProxyProcessor,
        ForwardToProcessor,
        HeaderMapPolicy,
    )
"""

from __future__ import annotations

from app.dsl.engine.processors.proxy.expose import (
    ExposeProxyProcessor,
    ProxyInboundSpec,
)
from app.dsl.engine.processors.proxy.forward import (
    ForwardToProcessor,
    ProxyOutboundSpec,
)
from app.dsl.engine.processors.proxy.headers import HeaderMapPolicy

__all__ = (
    "ExposeProxyProcessor",
    "ForwardToProcessor",
    "HeaderMapPolicy",
    "ProxyInboundSpec",
    "ProxyOutboundSpec",
)
