"""D-AUDIT-04 fix (cycle 1): AuthValidateProcessor — canonical _VERIFIERS path + fail-closed.

Канонический путь: ``src.backend.core.auth.auth_selector`` (вместо legacy
entrypoints.api.dependencies.auth_selector, который был DEPRECATED shim без _VERIFIERS).

Pure ASGI runtime assertions:
1. ``_load_verifiers()`` возвращает ≥7 verifier'ов из core.auth.auth_selector.
2. При monkeypatch'е ``_VERIFIERS`` атрибута в auth_selector module → raise AuthenticationProviderUnavailableError.
3. При monkeypatch'е ``importlib.import_module`` → raise AuthenticationProviderUnavailableError.
4. ``process()`` с недоступным реестром → exchange.stopped + error (fail-closed).
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.auth import AuthMethod
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.security import (
    AuthenticationProviderUnavailableError,
    AuthValidateProcessor,
    _load_verifiers,
)


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestAuthValidateCanonicalPath:
    """D-AUDIT-04 fix (cycle 1): canonical _VERIFIERS path resolves correctly."""

    def test_load_verifiers_returns_seven_auth_methods(self) -> None:
        """Канонический путь возвращает ≥7 verifier'ов из core.auth.auth_selector."""
        verifiers = _load_verifiers()
        assert len(verifiers) >= 7, (
            f"Ожидалось ≥7 verifier'ов, получено {len(verifiers)}"
        )
        expected_methods = {
            AuthMethod.API_KEY,
            AuthMethod.JWT,
            AuthMethod.BASIC,
            AuthMethod.MTLS,
            AuthMethod.SAML,
            AuthMethod.EXPRESS,
            AuthMethod.EXPRESS_JWT,
        }
        missing = expected_methods - set(verifiers.keys())
        assert not missing, f"Отсутствуют методы: {missing}"


class TestAuthValidateFailClosed:
    """D-AUDIT-04: pure ASGI runtime — fail-closed при недоступности реестра."""

    def test_load_verifiers_raises_when_verifiers_is_none(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_VERIFIERS=None в core.auth.auth_selector → raise AuthenticationProviderUnavailableError.

        D-AUDIT-04 fail-closed: явная недоступность атрибута → RuntimeError,
        не silent return {} (что было до cycle-1 fix).
        """
        # Patch атрибут _VERIFIERS в уже-импортированном модуле
        import src.backend.core.auth.auth_selector as auth_sel

        monkeypatch.setattr(auth_sel, "_VERIFIERS", None)

        # _load_verifiers читает _VERIFIERS через getattr(module, "_VERIFIERS", None) →
        # теперь видит None → raise AuthenticationProviderUnavailableError
        with pytest.raises(AuthenticationProviderUnavailableError):
            _load_verifiers()

    def test_load_verifiers_raises_when_module_import_fails(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """import_module('core.auth.auth_selector') → ImportError → raise.

        D-AUDIT-04 fail-closed: import failure → RuntimeError, не silent return {}.

        Подход: monkeypatch атрибут ``_VERIFIERS_MODULE`` строки в security.py на
        несуществующий модуль — _load_verifiers попытается его импортировать,
        получит ImportError и поднимет AuthenticationProviderUnavailableError.
        """
        # Меняем константу пути на несуществующий модуль
        import src.backend.dsl.engine.processors.security as security_mod

        monkeypatch.setattr(security_mod, "_VERIFIERS_MODULE", "nonexistent.module.that.does.not.exist")

        with pytest.raises(AuthenticationProviderUnavailableError):
            security_mod._load_verifiers()

    @pytest.mark.asyncio
    async def test_process_stops_exchange_on_provider_unavailable(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """_load_verifiers → AuthenticationProviderUnavailableError → exchange.stopped."""
        # Подменяем константу на несуществующий модуль → ImportError → AuthenticationProviderUnavailableError
        import src.backend.dsl.engine.processors.security as security_mod

        monkeypatch.setattr(security_mod, "_VERIFIERS_MODULE", "nonexistent.module.that.does.not.exist")

        proc = AuthValidateProcessor(["jwt"], required=True)
        exchange = _ex({})
        exchange.set_property("request", MagicMock())
        await proc.process(exchange, None)  # type: ignore[arg-type]

        assert exchange.stopped
        assert exchange.error is not None
        assert "provider" in exchange.error.lower() or "unavailable" in exchange.error.lower()
