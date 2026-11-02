"""Невалидное тело в auto-поверхности → 422, а не 500 (smoke 2026-10-29).

Дефект: ``POST /api/v1/auto/<action>`` с мусорным телом приводил к 500 —
``TypeError`` из ``method(**payload)`` (например, ``admin.get_config`` не
принимает поле ``data``, в которое мусорное тело оборачивается).

Контракт фикса: тело, не совпадающее с формой action'а → 422 с описанием
ожидаемой формы тела (ADR-0421 — fail-closed на границе доверия).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.dsl.commands.action_registry import ActionHandlerRegistry
from src.backend.entrypoints.api.generator.auto_register import (
    _AUTO_PREFIX,
    auto_register_unrouted_actions,
)

pytestmark = pytest.mark.unit


class _NoArgService:
    """Action без параметров тела (как ``admin.get_config``)."""

    async def get_config(self) -> dict[str, Any]:
        """Возвращает конфиг-заглушку."""
        return {"ok": True}


class _DataArgService:
    """Action, принимающий произвольное тело в параметре ``data``."""

    async def do_thing(self, data: Any = None) -> dict[str, Any]:
        """Эхо полученного тела."""
        return {"received": data}


def _client_for(service: Any, method: str, action: str) -> TestClient:
    """Собирает TestClient с одним auto-роутом на ``action``."""
    registry = ActionHandlerRegistry()
    registry.register(
        action=action, service_getter=lambda: service, service_method=method
    )
    app = FastAPI()
    auto_register_unrouted_actions(app, registry)
    return TestClient(app, raise_server_exceptions=False)


class TestGarbageBodyIsRejected:
    """Мусорное тело → 422 (не 500)."""

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param(["garbage", 1], id="list"),
            pytest.param("garbage", id="string"),
            pytest.param(42, id="number"),
            pytest.param(True, id="bool"),
        ],
    )
    def test_non_object_body_returns_422(self, body: Any) -> None:
        """Не-JSON-объект в теле → 422 вместо 500."""
        client = _client_for(_NoArgService(), "get_config", "demo.get_config")

        response = client.post(f"{_AUTO_PREFIX}/demo.get_config", json=body)

        assert response.status_code == 422, response.text
        assert response.status_code != 500

    def test_unexpected_field_returns_422(self) -> None:
        """Лишнее поле в теле → 422 вместо 500."""
        client = _client_for(_NoArgService(), "get_config", "demo.get_config")

        response = client.post(
            f"{_AUTO_PREFIX}/demo.get_config", json={"unexpected": 1}
        )

        assert response.status_code == 422, response.text

    def test_error_detail_describes_expected_shape(self) -> None:
        """Ответ 422 описывает ожидаемую форму тела."""
        client = _client_for(_NoArgService(), "get_config", "demo.get_config")

        response = client.post(f"{_AUTO_PREFIX}/demo.get_config", json=["garbage"])

        detail = response.json()["detail"]
        assert detail["code"] == "invalid_request_body"
        assert detail["action"] == "demo.get_config"
        assert detail["reason"]
        assert "JSON" in detail["detail"] or "ожидаем" in detail["detail"].lower()
        assert "expected_fields" in detail


class TestValidRequestsStillWork:
    """Валидные запросы не сломаны (регрессия фикса)."""

    def test_empty_object_body_is_accepted(self) -> None:
        """Пустой JSON-объект → 200."""
        client = _client_for(_NoArgService(), "get_config", "demo.get_config")

        response = client.post(f"{_AUTO_PREFIX}/demo.get_config", json={})

        assert response.status_code == 200, response.text
        assert response.json() == {"ok": True}

    def test_non_object_body_reaches_data_parameter(self) -> None:
        """Action с параметром ``data`` по-прежнему получает тело как ``data``."""
        client = _client_for(_DataArgService(), "do_thing", "demo.do_thing")

        response = client.post(f"{_AUTO_PREFIX}/demo.do_thing", json=["a", "b"])

        assert response.status_code == 200, response.text
        assert response.json() == {"received": ["a", "b"]}
