"""Wave 1.2 (Roadmap V10) — unit-тесты ``auto_register_unrouted_actions``.

Покрывает:

* пустой реестр → 0 добавленных роутов;
* один action без существующего роута → 1 авто-роут на ``/api/v1/auto/<action>``;
* идемпотентность повторного вызова;
* skip уже существующих роутов (по совпадению имени с action);
* skip роутов с именем ``auto.<action>`` (повторный auto-register);
* выбор HTTP-метода по CRUD-конвенции (``list``/``get`` → GET,
  ``create`` → POST, ``update`` → PUT, ``delete`` → DELETE);
* fallback на POST для не-CRUD action;
* фактический вызов авто-эндпоинта через ``TestClient`` делегирует в
  ``registry.dispatch``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from src.backend.dsl.commands.action_registry import ActionHandlerRegistry
from src.backend.entrypoints.api.generator.auto_register import (
    _AUTO_PREFIX,
    _infer_method_for_action,
    auto_register_unrouted_actions,
)


class _FakeService:
    """Простая заглушка-сервис для регистрации в ``ActionHandlerRegistry``."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def do_thing(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("do_thing", kwargs))
        return {"ok": True, "received": kwargs}

    async def get(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get", kwargs))
        return {"items": [], "args": kwargs}


def _service_getter(service: _FakeService):
    """Замыкание-фабрика для регистрации сервиса в реестре."""
    return lambda: service


@pytest.fixture
def registry() -> ActionHandlerRegistry:
    """Изолированный реестр на тест."""
    return ActionHandlerRegistry()


@pytest.fixture
def app() -> FastAPI:
    """Чистый FastAPI-app без роутов."""
    return FastAPI()


class TestInferMethodForAction:
    @pytest.mark.parametrize(
        ("action", "expected"),
        [
            ("orders.list", "GET"),
            ("orders.get", "GET"),
            ("orders.create", "POST"),
            ("orders.create_many", "POST"),
            ("orders.update", "PUT"),
            ("orders.delete", "DELETE"),
            # Fallback: неизвестный verb → POST.
            ("orders.send_email", "POST"),
            # Fallback: action без точки → POST.
            ("ping", "POST"),
        ],
    )
    def test_method_inference(self, action: str, expected: str) -> None:
        assert _infer_method_for_action(action) == expected


class TestAutoRegisterUnroutedActions:
    def test_empty_registry_adds_zero_routes(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        added = auto_register_unrouted_actions(app, registry)
        assert added == 0
        assert not any(
            isinstance(r, APIRoute) and r.path.startswith(_AUTO_PREFIX)
            for r in app.routes
        )

    def test_single_action_creates_one_route(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        service = _FakeService()
        registry.register(
            action="demo.do_thing",
            service_getter=_service_getter(service),
            service_method="do_thing",
        )
        added = auto_register_unrouted_actions(app, registry)
        assert added == 1
        # Проверяем, что роут реально добавлен на ожидаемом пути.
        paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
        assert f"{_AUTO_PREFIX}/demo.do_thing" in paths

    def test_idempotent_second_call_adds_zero(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        service = _FakeService()
        registry.register(
            action="demo.do_thing",
            service_getter=_service_getter(service),
            service_method="do_thing",
        )
        first = auto_register_unrouted_actions(app, registry)
        second = auto_register_unrouted_actions(app, registry)
        assert first == 1
        assert second == 0

    def test_skip_action_with_existing_route_name(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        # Имитируем: action ``healthcheck_database`` уже имеет роут
        # с тем же именем (исторический ActionSpec.name == action).
        async def existing_endpoint() -> dict[str, str]:
            return {"status": "ok"}

        app.add_api_route(
            path="/healthcheck_database",
            endpoint=existing_endpoint,
            methods=["GET"],
            name="healthcheck_database",
        )
        service = _FakeService()
        registry.register(
            action="healthcheck_database",
            service_getter=_service_getter(service),
            service_method="do_thing",
        )
        added = auto_register_unrouted_actions(app, registry)
        assert added == 0

    def test_crud_verb_picks_correct_http_method(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        service = _FakeService()
        for verb, expected_method in [
            ("list", "GET"),
            ("create", "POST"),
            ("update", "PUT"),
            ("delete", "DELETE"),
        ]:
            registry.register(
                action=f"products.{verb}",
                service_getter=_service_getter(service),
                service_method="do_thing",
            )
        added = auto_register_unrouted_actions(app, registry)
        assert added == 4

        method_by_path: dict[str, set[str]] = {}
        for route in app.routes:
            if isinstance(route, APIRoute) and route.path.startswith(_AUTO_PREFIX):
                method_by_path[route.path] = set(route.methods or ())

        assert "GET" in method_by_path[f"{_AUTO_PREFIX}/products.list"]
        assert "POST" in method_by_path[f"{_AUTO_PREFIX}/products.create"]
        assert "PUT" in method_by_path[f"{_AUTO_PREFIX}/products.update"]
        assert "DELETE" in method_by_path[f"{_AUTO_PREFIX}/products.delete"]

    def test_non_crud_action_defaults_to_post(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        service = _FakeService()
        registry.register(
            action="email.send",
            service_getter=_service_getter(service),
            service_method="do_thing",
        )
        added = auto_register_unrouted_actions(app, registry)
        assert added == 1
        for route in app.routes:
            if isinstance(route, APIRoute) and route.path.endswith("/email.send"):
                assert "POST" in route.methods

    def test_endpoint_dispatches_to_registry(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        service = _FakeService()
        registry.register(
            action="demo.do_thing",
            service_getter=_service_getter(service),
            service_method="do_thing",
        )
        auto_register_unrouted_actions(app, registry)

        client = TestClient(app)
        response = client.post(
            f"{_AUTO_PREFIX}/demo.do_thing",
            json={"foo": "bar"},
        )
        assert response.status_code == 200
        assert response.json() == {"ok": True, "received": {"foo": "bar"}}
        assert service.calls == [("do_thing", {"foo": "bar"})]

    def test_get_endpoint_uses_query_params(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        # Для GET-action параметры ожидаются в query, а не body.
        service = _FakeService()
        registry.register(
            action="orders.list",
            service_getter=_service_getter(service),
            service_method="get",
        )
        auto_register_unrouted_actions(app, registry)

        client = TestClient(app)
        response = client.get(f"{_AUTO_PREFIX}/orders.list?page=1&size=10")
        assert response.status_code == 200
        body = response.json()
        assert body["items"] == []
        assert body["args"] == {"page": "1", "size": "10"}

    def test_returns_default_registry_when_omitted(
        self, app: FastAPI
    ) -> None:
        # Без явного ``registry`` функция использует глобальный
        # ``action_handler_registry`` — тест проверяет лишь, что вызов
        # не падает (число добавленных зависит от глобального состояния).
        added = auto_register_unrouted_actions(app)
        assert added >= 0

    def test_double_call_does_not_create_duplicate_route(
        self, app: FastAPI, registry: ActionHandlerRegistry
    ) -> None:
        service = _FakeService()
        registry.register(
            action="demo.do_thing",
            service_getter=_service_getter(service),
            service_method="do_thing",
        )
        auto_register_unrouted_actions(app, registry)
        auto_register_unrouted_actions(app, registry)
        # Должен быть ровно один роут с этим именем.
        matching = [
            r
            for r in app.routes
            if isinstance(r, APIRoute) and r.name == "auto.demo.do_thing"
        ]
        assert len(matching) == 1
