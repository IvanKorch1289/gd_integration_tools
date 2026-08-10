"""Core middleware primitives placeholder (S171 M28, D293).

Per project convention (V22 / S171 M28), HTTP middleware implementations
live in :mod:`src.backend.entrypoints.middlewares` and are registered
through the 4-layer ordering in
:mod:`src.backend.entrypoints.middlewares.setup_middlewares`.

The core layer contributes only contracts and cross-cutting helpers
that middleware may use:

* :class:`src.backend.core.resilience.timeout_helper.with_timeout`
* :class:`src.backend.core.middleware.policies` (declarative policies)

No concrete ASGI middleware class ships from ``core.middleware`` by
design — the entrypoint layer owns the HTTP request lifecycle. Future
ADR-driven re-import (per D293) may move selected middlewares here.
"""
from __future__ import annotations as annotations

__all__: tuple[str, ...] = ()
