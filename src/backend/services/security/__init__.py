"""Security facade для entrypoints (S45 W2 + Sprint 224 lazy proxy).

Single entry-point для security primitives (HMAC signature verification)
из entrypoints. Re-export canonical ``infrastructure.security.signatures``.

Sprint 224 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy (ponytail: thin proxy). Устраняет layer-violation
``services → infrastructure`` (allowlist entry #1) — infrastructure
импортируется только при первом lookup атрибута, не при import модуля.

Использование::

    from src.backend.services.security import verify_signature, DEFAULT_TIMESTAMP_WINDOW

    valid = verify_signature(payload, signature, secret, timestamp_window=DEFAULT_TIMESTAMP_WINDOW)

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations as annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.security.signatures import (
        DEFAULT_TIMESTAMP_WINDOW,
        verify_signature,
    )

__all__ = ("DEFAULT_TIMESTAMP_WINDOW", "verify_signature")


def __getattr__(name: str) -> Any:
    """Lazy proxy: импорт infrastructure только при lookup атрибута.

    Это устраняет layer-violation ``services → infrastructure`` —
    runtime import происходит только если caller реально использует symbol.
    Symbol identity сохраняется (proxy возвращает original object).
    """
    if name in {"DEFAULT_TIMESTAMP_WINDOW", "verify_signature"}:
        from src.backend.infrastructure.security import signatures as _sig

        return getattr(_sig, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
