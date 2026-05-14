"""Smoke-тесты для Admin Action-Bus + Plugin-Marketplace endpoints (K5 W4).

Проверяет:
    - 503 при выключенном feature_flag.admin_marketplace_endpoints;
    - корректный список actions при включённом флаге (mock registry);
    - сериализацию payload при вызове action;
    - 503 для plugins при выключенном флаге;
    - toggle плагина (mock registry).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# ─── Вспомогательные фикстуры ─────────────────────────────────────────────────


def _make_actions_app(flag_on: bool) -> FastAPI:
    """Создаёт тестовое FastAPI-приложение с router admin_actions."""
    from src.backend.entrypoints.api.v1.endpoints.admin_actions import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


def _make_plugins_app(flag_on: bool) -> FastAPI:
    """Создаёт тестовое FastAPI-приложение с router admin_plugins."""
    from src.backend.entrypoints.api.v1.endpoints.admin_plugins import router

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


# ─── Тесты Actions ────────────────────────────────────────────────────────────


def test_actions_list_returns_503_when_flag_off() -> None:
    """GET /admin/actions/list возвращает 503, если feature_flag выключен."""
    import src.backend.entrypoints.api.v1.endpoints.admin_actions as actions_mod

    app = _make_actions_app(flag_on=False)

    # Патчим _check_flag_enabled так, чтобы он выбрасывал 503 (имитирует выключенный flag)
    from fastapi import HTTPException
    from fastapi import status as http_status

    def _raise_503() -> None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="флаг выключен",
        )

    with patch.object(actions_mod, "_check_flag_enabled", side_effect=_raise_503):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/actions/list")

    assert resp.status_code == 503


def test_actions_list_returns_data_when_flag_on() -> None:
    """GET /admin/actions/list возвращает список при включённом флаге (mock)."""
    app = _make_actions_app(flag_on=True)

    # Патчим feature_flags и реестр actions
    mock_spec = MagicMock()
    mock_spec.name = "test.action"
    mock_spec.description = "Тестовый action"
    mock_spec.namespace = "test"
    mock_spec.tier = "1"

    mock_registry = MagicMock()
    mock_registry.list_all.return_value = [mock_spec]

    import src.backend.entrypoints.api.v1.endpoints.admin_actions as actions_mod

    with patch.object(
        actions_mod,
        "_check_flag_enabled",
        return_value=None,  # флаг "включён"
    ), patch.object(
        actions_mod,
        "_get_registry",
        return_value=mock_registry,
    ):
        client = TestClient(app)
        resp = client.get("/api/v1/admin/actions/list")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["name"] == "test.action"
    assert data[0]["namespace"] == "test"


def test_actions_invoke_serializes_payload() -> None:
    """POST /admin/actions/invoke правильно передаёт payload и возвращает результат."""
    app = _make_actions_app(flag_on=True)

    mock_registry = MagicMock()

    async def _fake_invoke(name: str, payload: dict, mode: str) -> dict[str, Any]:
        """Имитирует вызов action."""
        return {"status": "ok", "value": 42, "name": name, "payload": payload}

    mock_registry.invoke = _fake_invoke

    import src.backend.entrypoints.api.v1.endpoints.admin_actions as actions_mod

    with patch.object(
        actions_mod,
        "_check_flag_enabled",
        return_value=None,
    ), patch.object(
        actions_mod,
        "_get_registry",
        return_value=mock_registry,
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/admin/actions/invoke",
            json={"name": "test.action", "payload": {"key": "value"}, "mode": "sync"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "test.action"
    assert data["mode"] == "sync"
    assert "result" in data


# ─── Тесты Plugins ────────────────────────────────────────────────────────────


def test_plugins_list_returns_503_when_flag_off() -> None:
    """GET /admin/plugins/list возвращает 503, если feature_flag выключен."""
    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as plugins_mod

    app = _make_plugins_app(flag_on=False)

    from fastapi import HTTPException
    from fastapi import status as http_status

    def _raise_503() -> None:
        raise HTTPException(
            status_code=http_status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="флаг выключен",
        )

    with patch.object(plugins_mod, "_check_flag_enabled", side_effect=_raise_503):
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/api/v1/admin/plugins/list")

    assert resp.status_code == 503


def test_plugins_toggle_updates_status() -> None:
    """POST /admin/plugins/{name}/toggle обновляет статус плагина (mock)."""
    app = _make_plugins_app(flag_on=True)

    import src.backend.entrypoints.api.v1.endpoints.admin_plugins as plugins_mod

    # При недоступном реестре endpoint возвращает mock-ответ с правильными полями
    with patch.object(
        plugins_mod,
        "_check_flag_enabled",
        return_value=None,
    ), patch.object(
        plugins_mod,
        "_get_plugin_registry",
        return_value=None,  # mock-путь через _get_plugin_registry → None
    ):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/admin/plugins/core_entities/toggle",
            json={"active": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "core_entities"
    assert data["active"] is True
    assert data["current_status"] == "active"
    assert data["previous_status"] == "inactive"
