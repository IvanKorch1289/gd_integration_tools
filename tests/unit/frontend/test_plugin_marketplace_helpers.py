"""Smoke-тесты для plugin_marketplace_client.

Проверяют поведение трёх публичных функций без запущенного backend:
mock-fallback для list_plugins, обработку 404 в get_plugin_manifest,
сериализацию запроса в toggle_plugin, фильтрацию по статусу.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Тест 1: list_plugins возвращает inmemory-fallback при недоступном backend
# ---------------------------------------------------------------------------


def test_list_plugins_inmemory_fallback() -> None:
    """list_plugins возвращает mock-список при ConnectError (backend down).

    При любой транспортной ошибке функция должна вернуть не пустой список
    словарей с обязательными ключами: name, version, status, capabilities.
    """
    import httpx

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services.plugin_marketplace_client import (
            list_plugins,
        )

        result = list_plugins()

    assert isinstance(result, list), "Должен вернуть список"
    assert len(result) > 0, "Mock-fallback не должен быть пустым"
    first = result[0]
    for key in ("name", "version", "status", "capabilities"):
        assert key in first, f"Ключ '{key}' отсутствует в plugin-словаре"


# ---------------------------------------------------------------------------
# Тест 2: get_plugin_manifest возвращает None при HTTP 404
# ---------------------------------------------------------------------------


def test_get_plugin_manifest_returns_none_on_404() -> None:
    """get_plugin_manifest возвращает None при HTTP 404 от backend.

    Проверяет, что при ответе 404 функция не поднимает исключение и
    возвращает None, а не mock-данные.
    """
    mock_response = MagicMock()
    mock_response.status_code = 404

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services.plugin_marketplace_client import (
            get_plugin_manifest,
        )

        result = get_plugin_manifest("nonexistent_plugin_xyz")

    assert result is None, "При 404 должен вернуть None"


# ---------------------------------------------------------------------------
# Тест 3: toggle_plugin сериализует запрос с name и active
# ---------------------------------------------------------------------------


def test_toggle_plugin_serializes_request() -> None:
    """toggle_plugin отправляет POST с JSON-телом {name, active}.

    Проверяет, что при успешном HTTP 200 функция возвращает True,
    а тело запроса содержит поля name и active с правильными значениями.
    """
    mock_response = MagicMock()
    mock_response.status_code = 200

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.post.return_value = mock_response
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services.plugin_marketplace_client import (
            toggle_plugin,
        )

        result = toggle_plugin("notification_hub", active=False)

    assert result is True, "При HTTP 200 должен вернуть True"
    call_kwargs = mock_client.post.call_args
    body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json") or call_kwargs[0][1]
    assert body["name"] == "notification_hub", "Поле name должно передаваться корректно"
    assert body["active"] is False, "Поле active должно соответствовать аргументу"


# ---------------------------------------------------------------------------
# Тест 4: list_plugins фильтрует по status_filter
# ---------------------------------------------------------------------------


def test_list_plugins_filter_by_status() -> None:
    """list_plugins с status_filter='active' возвращает только активные плагины.

    При ConnectError используется mock-fallback; проверяем, что после
    применения фильтра 'active' все возвращённые записи имеют status='active'.
    """
    import httpx

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        from src.frontend.streamlit_app.services.plugin_marketplace_client import (
            list_plugins,
        )

        result = list_plugins(status_filter="active")

    assert isinstance(result, list), "Должен вернуть список"
    assert len(result) > 0, "Mock-fallback должен содержать хотя бы один active плагин"
    for plugin in result:
        assert plugin.get("status") == "active", (
            f"Плагин '{plugin.get('name')}' имеет статус '{plugin.get('status')}', "
            "ожидался 'active'"
        )
