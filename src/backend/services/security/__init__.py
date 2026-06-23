"""Security facade для entrypoints (S45 W2).

Single entry-point для security primitives (HMAC signature verification)
из entrypoints. Re-export canonical ``infrastructure.security.signatures``.

Использование::

    from src.backend.services.security import verify_signature, DEFAULT_TIMESTAMP_WINDOW

    valid = verify_signature(payload, signature, secret, timestamp_window=DEFAULT_TIMESTAMP_WINDOW)

Layer policy: entrypoints -> services (allowed per V22).
"""

from __future__ import annotations

from src.backend.infrastructure.security.signatures import (  # noqa: E402,F401
    DEFAULT_TIMESTAMP_WINDOW,
    verify_signature,
)

__all__ = ("DEFAULT_TIMESTAMP_WINDOW", "verify_signature")
