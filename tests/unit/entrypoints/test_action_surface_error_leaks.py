"""ADR-0421 — утечки внутренних ошибок в HTTP/SOAP-ответах.

До ADR-0421 наружу уходили:

* ``legacy_aliases.py`` → ``{"detail": "Action dispatch failed: {exc}"}``;
* ``soap_handler.py`` → SOAP Fault ``Server`` с ``str(exc)``;
* ``admin_connectors.py`` → ``{"detail": "Reload failed: {type}: {exc}"}``
  и ``str(exc)`` в теле ответа.

Теперь детали — только в лог, наружу — безопасное сообщение.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.generator.legacy_aliases import register_legacy_aliases
from src.backend.entrypoints.api.v1.endpoints.admin_connectors import (
    _AdminConnectorsFacade,
)

#: Маркер, который не должен попадать в ответ наружу.
_SECRET = "SUPER_SECRET_VALUE_42"

# ──────────────────────────────────────────────────────────────────────
#  Legacy URL-алиасы
# ──────────────────────────────────────────────────────────────────────


def _legacy_client() -> TestClient:
    app = FastAPI()
    register_legacy_aliases(app)
    return TestClient(app, raise_server_exceptions=False)


class TestLegacyAliasErrorLeak:
    """``/api/v1/orders/all/`` и др. — детали ошибки не уходят наружу."""

    def test_internal_error_detail_hidden(self) -> None:
        client = _legacy_client()
        registry = MagicMock()
        registry.dispatch = AsyncMock(side_effect=RuntimeError(_SECRET))

        with patch("src.backend.core.api.extensions.action_handler_registry", registry):
            response = client.get("/api/v1/orders/all/")

        assert response.status_code == 500
        assert _SECRET not in response.text
        assert response.json()["detail"] == "Action dispatch failed"

    def test_permission_denied_returns_403(self) -> None:
        """Нет прав → 403 (ADR-0421), а не 500."""
        from src.backend.dsl.commands.action_registry import ActionPermissionDeniedError

        client = _legacy_client()
        registry = MagicMock()
        registry.dispatch = AsyncMock(
            side_effect=ActionPermissionDeniedError(
                action="orders.get", required=("role:admin",), missing=("role:admin",)
            )
        )

        with patch("src.backend.core.api.extensions.action_handler_registry", registry):
            response = client.get("/api/v1/orders/all/")

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "action_permission_denied"


# ──────────────────────────────────────────────────────────────────────
#  SOAP
# ──────────────────────────────────────────────────────────────────────


class _FakeRequest:
    """Минимальный stub FastAPI-Request для SOAP-обработчика."""

    def __init__(self, body: bytes, auth: Any = None) -> None:
        self._body = body
        self.state = SimpleNamespace(auth=auth)
        self.headers: dict[str, str] = {}

    async def body(self) -> bytes:
        return self._body


_SOAP_ENVELOPE = (
    '<?xml version="1.0"?>'
    '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
    "<soap:Body><unknown_op/></soap:Body></soap:Envelope>"
).encode()


class TestSoapFaultLeak:
    """SOAP Fault не должен содержать ``str(exc)``."""

    async def test_internal_error_fault_is_generic(self) -> None:
        from src.backend.entrypoints.soap.soap_handler import handle_soap_request

        dsl = MagicMock()
        dsl.dispatch = AsyncMock(side_effect=RuntimeError(_SECRET))

        with patch(
            "src.backend.entrypoints.soap.soap_handler.get_dsl_service",
            return_value=dsl,
        ):
            response = await handle_soap_request(_FakeRequest(_SOAP_ENVELOPE))

        body = response.body.decode()
        assert response.status_code == 500
        assert _SECRET not in body
        assert "Internal server error" in body

    async def test_dsl_error_not_leaked(self) -> None:
        """Ошибка DSL-pipeline тоже не уходит в fault."""
        from src.backend.dsl.engine.exchange import Exchange
        from src.backend.entrypoints.soap.soap_handler import handle_soap_request

        exchange = Exchange()
        exchange.error = _SECRET
        dsl = MagicMock()
        dsl.dispatch = AsyncMock(return_value=exchange)

        with patch(
            "src.backend.entrypoints.soap.soap_handler.get_dsl_service",
            return_value=dsl,
        ):
            response = await handle_soap_request(_FakeRequest(_SOAP_ENVELOPE))

        body = response.body.decode()
        assert response.status_code == 500
        assert _SECRET not in body


# ──────────────────────────────────────────────────────────────────────
#  Admin connectors
# ──────────────────────────────────────────────────────────────────────


class TestAdminConnectorsErrorLeak:
    """Ошибка reload коннектора не уходит в HTTP-ответ."""

    async def test_reload_failure_detail_is_safe(self) -> None:
        class _NotRegisteredError(Exception):
            """Заглушка вместо ``ConnectorNotRegisteredError``."""

        registry = MagicMock()
        registry.reload = AsyncMock(side_effect=RuntimeError(_SECRET))

        with (
            patch(
                "src.backend.core.di.providers.get_connector_registry_provider",
                return_value=registry,
            ),
            patch(
                "src.backend.core.di.providers.get_connector_registry_errors_provider",
                return_value=_NotRegisteredError,
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await _AdminConnectorsFacade().reload_connector(name="pg")

        assert exc.value.status_code == 500
        assert _SECRET not in str(exc.value.detail)
        assert exc.value.detail == "Connector reload failed"

    async def test_post_reload_health_error_is_safe(self) -> None:
        class _NotRegisteredError(Exception):
            """Заглушка вместо ``ConnectorNotRegisteredError``."""

        registry = MagicMock()
        registry.reload = AsyncMock(return_value=12.5)
        registry.get = MagicMock(side_effect=RuntimeError(_SECRET))

        with (
            patch(
                "src.backend.core.di.providers.get_connector_registry_provider",
                return_value=registry,
            ),
            patch(
                "src.backend.core.di.providers.get_connector_registry_errors_provider",
                return_value=_NotRegisteredError,
            ),
        ):
            result = await _AdminConnectorsFacade().reload_connector(name="pg")

        assert _SECRET not in str(result)
        assert result["post_reload_health"]["error"] == "RuntimeError"
