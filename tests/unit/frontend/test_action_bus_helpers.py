"""Smoke-тесты для action_bus_client.

Проверяют поведение трёх публичных функций без запущенного backend:
mock-fallback для list_actions, сериализацию payload при invoke,
обработку ошибочного HTTP-ответа, возврат None при 404 в get_action_spec.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Тест 1: list_actions возвращает inmemory-fallback при недоступном backend
# ---------------------------------------------------------------------------


def test_list_actions_inmemory_fallback() -> None:
    """list_actions возвращает mock-список при ConnectError (backend down).

    При любой транспортной ошибке функция должна вернуть не пустой список
    словарей с обязательными ключами: name, description, namespace, tier.
    """
    import httpx

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services.action_bus_client import list_actions

        result = list_actions()

    assert isinstance(result, list), "Должен вернуть список"
    assert len(result) > 0, "Mock-fallback не должен быть пустым"
    first = result[0]
    for key in ("name", "description", "namespace", "tier"):
        assert key in first, f"Ключ '{key}' отсутствует в action-словаре"


# ---------------------------------------------------------------------------
# Тест 2: invoke правильно сериализует payload и отправляет в тело POST
# ---------------------------------------------------------------------------


def test_invoke_serializes_payload() -> None:
    """invoke отправляет JSON-тело с action, payload, mode.

    Проверяет, что при успешном HTTP-ответе 200 функция возвращает
    именно тело ответа сервера как словарь.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "result": {"score": 42}}

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services.action_bus_client import invoke

        result = invoke("orders.create", {"order_id": 99}, "sync")

    assert result == {"status": "ok", "result": {"score": 42}}
    # Убеждаемся, что payload передан корректно
    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
    assert body["action"] == "orders.create"
    assert body["payload"] == {"order_id": 99}
    assert body["mode"] == "sync"


# ---------------------------------------------------------------------------
# Тест 3: invoke возвращает error-dict при HTTP 4xx/5xx
# ---------------------------------------------------------------------------


def test_invoke_handles_error_response() -> None:
    """invoke возвращает словарь с ключом 'error' при HTTP 400+.

    Проверяет, что при HTTP 422 функция не поднимает исключение, а
    возвращает dict с ключами error и detail.
    """
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.json.return_value = {"detail": "Validation error"}

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services import action_bus_client

        result = action_bus_client.invoke("bad.action", {}, "sync")

    assert "error" in result, "При HTTP 4xx должен быть ключ 'error'"
    assert "422" in result["error"], "Код ответа должен присутствовать в поле error"
    assert "detail" in result, "Поле 'detail' должно присутствовать"


# ---------------------------------------------------------------------------
# Тест 4: get_action_spec возвращает None при HTTP 404
# ---------------------------------------------------------------------------


def test_get_action_spec_returns_none_for_missing() -> None:
    """get_action_spec возвращает None при HTTP 404 от backend.

    Проверяет, что при ответе 404 функция не поднимает исключение и
    возвращает None, не заглушку из mock-словаря.
    """
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services.action_bus_client import (
            get_action_spec,
        )

        result = get_action_spec("nonexistent.action.xyz")

    assert result is None, "При 404 должен вернуть None"
