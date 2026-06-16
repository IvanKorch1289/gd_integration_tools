"""DEPRECATED shim — реальная implementation переехала в ``core.auth.auth_selector``.

S96 W1: ``core.auth.auth_selector`` стал каноническим путём. Этот модуль
оставлен для backward compat (10 файлов импортируют ``require_auth``,
``set_default_auth``, ``verify_request``, ``AuthMethod``, ``AuthContext``
отсюда). Удалится в S99+ — к этому моменту все импорты должны быть
переведены на ``src.backend.core.auth.gateway`` или
``src.backend.core.auth.auth_selector``.

Issue: S96 W1 — downward layer violation ``core/auth/gateway.py →
entrypoints/api/dependencies/auth_selector``. Resolved by relocating
implementation to core.

Используйте ``src.backend.core.auth.gateway`` в новых расширениях::

    from src.backend.core.auth.gateway import (
        AuthContext,
        AuthMethod,
        require_auth,
        set_default_auth,
        verify_request,
    )
"""

from __future__ import annotations

import warnings

# Re-export public API из канонической локации.
# Эти импорты идут ПОСЛЕ warnings, чтобы import-time message сработал.
from src.backend.core.auth.auth_selector import (  # noqa: E402
    _VERIFIERS,
    AuthContext,
    AuthMethod,
    require_auth,
    set_default_auth,
    verify_request,
)

warnings.warn(
    "Importing from src.backend.entrypoints.api.dependencies.auth_selector "
    "is deprecated. Use src.backend.core.auth.gateway instead "
    "(S96 W1 — implementation relocated to core.auth.auth_selector).",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = (
    "AuthContext",
    "AuthMethod",
    "_VERIFIERS",
    "require_auth",
    "set_default_auth",
    "verify_request",
)
