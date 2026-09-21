"""Regression-тест распространения JWT из login в page API client."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from src.frontend.streamlit_app.api_clients import base
from src.frontend.streamlit_app.api_clients.auth import AuthClient, LoginResponse
from src.frontend.streamlit_app.api_clients.generic import get_api_client
from src.frontend.streamlit_app.shared import auth_state


@pytest.mark.unit
def test_login_token_reaches_facade_domain_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """JWT после login попадает в реальный wrapper-вызов страницы."""
    session_state: dict[str, object] = {}
    monkeypatch.setattr(auth_state.st, "session_state", session_state)
    monkeypatch.setattr(base.st, "session_state", session_state)

    auth_client = MagicMock(spec=AuthClient)
    auth_client.login.return_value = LoginResponse(
        {
            "access_token": "jwt_after_login",
            "auth_method": "password",
            "username": "user",
        }
    )
    monkeypatch.setattr(auth_state, "_client", lambda: auth_client)
    auth_state.login(username="user", password="password")

    response = MagicMock(spec=httpx.Response)
    response.status_code = 200
    response.headers = {"content-type": "application/json"}
    response.json.return_value = []
    response.raise_for_status.return_value = None
    transport = MagicMock()
    transport.request.return_value = response
    transport.__enter__.return_value = transport
    transport.__exit__.return_value = False
    monkeypatch.setattr(httpx, "Client", lambda *args, **kwargs: transport)

    assert get_api_client().get_orders() == []
    assert transport.request.call_args.kwargs["headers"]["Authorization"] == (
        "Bearer jwt_after_login"
    )
