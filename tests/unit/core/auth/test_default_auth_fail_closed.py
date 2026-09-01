"""Unit-тесты ``core.auth.auth_selector`` fail-CLOSED default (S49 W2).

S49 W2 fix (P0 swarm-48 backlog #4): default ``_default_auth`` был
``AuthMethod.API_KEY`` — silent global fallback для ``require_auth(methods=None)``.
Если production не вызывает ``set_default_auth()`` явно → fallback на API_KEY
без логов. Риск: misconfigured prod → silent anonymous allowed.

Fix: default = ``None`` + ``RuntimeError`` в ``require_auth`` если не configured.
Fail-CLOSED: production MUST call ``set_default_auth()`` в startup.
"""

from __future__ import annotations

import pytest

from src.backend.core.auth import auth_selector
from src.backend.core.auth.auth_selector import (
    AuthMethod,
    require_auth,
    set_default_auth,
)


@pytest.mark.unit
class TestDefaultAuthFailClosed:
    """S49 W2: ``_default_auth=None`` → require_auth() без methods raises."""

    def test_require_auth_without_methods_raises_runtime_error(self) -> None:
        """``require_auth()`` без methods AND без ``set_default_auth()`` →
        ``RuntimeError`` (fail-CLOSED)."""
        # Force _default_auth to None (post-fix default; explicit reset).
        auth_selector._default_auth = None
        with pytest.raises(RuntimeError, match="set_default_auth"):
            require_auth()

    def test_require_auth_with_explicit_method_works(self) -> None:
        """``require_auth(methods=JWT)`` работает (explicit auth method)."""
        dep = require_auth(methods=AuthMethod.JWT)
        assert callable(dep)

    def test_set_default_auth_then_require_works(self) -> None:
        """``set_default_auth(JWT)`` → ``require_auth()`` без methods works."""
        set_default_auth(AuthMethod.JWT)
        dep = require_auth()
        assert callable(dep)
        # Cleanup: reset _default_auth to None (post-fix default).
        auth_selector._default_auth = None

    def test_require_auth_with_list_methods_works(self) -> None:
        """``require_auth(methods=[JWT, API_KEY])`` — list of methods."""
        dep = require_auth(methods=[AuthMethod.JWT, AuthMethod.API_KEY])
        assert callable(dep)

    def test_set_default_auth_to_list_works(self) -> None:
        """``set_default_auth([JWT, API_KEY])`` → require_auth() works."""
        set_default_auth([AuthMethod.JWT, AuthMethod.API_KEY])
        dep = require_auth()
        assert callable(dep)
        # Cleanup: reset _default_auth.
        auth_selector._default_auth = None


@pytest.mark.unit
class TestAuthGatewayRequireUsesInstanceDefault:
    """S49 W2: ``AuthGateway.require()`` passes ``_default_method`` явно."""

    def test_require_uses_default_method(self) -> None:
        """``AuthGateway(default_method=JWT).require()`` works без global state."""
        from src.backend.core.auth import gateway

        # Reset global _default_auth to ensure fallback is NOT used.
        auth_selector._default_auth = None

        g = gateway.AuthGateway(default_method=gateway.AuthMethod.JWT)
        dep = g.require()  # default
        assert callable(dep)

        # Custom methods (override).
        dep2 = g.require(methods=gateway.AuthMethod.API_KEY)
        assert callable(dep2)

    def test_require_default_method_api_key_works(self) -> None:
        """``AuthGateway(default_method=API_KEY).require()`` works."""
        from src.backend.core.auth import gateway

        auth_selector._default_auth = None

        g = gateway.AuthGateway(default_method=gateway.AuthMethod.API_KEY)
        dep = g.require()
        assert callable(dep)
