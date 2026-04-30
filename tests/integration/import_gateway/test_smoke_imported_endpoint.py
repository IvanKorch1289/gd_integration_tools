"""W24 deferred — smoke-test импорта OpenAPI и dispatch через action-registry.

Сценарий:
1. ``ImportService.import_and_register`` парсит ``petstore_minimal.yaml``.
2. Action'ы регистрируются в фейковом registry с positional API
   (повторяет фактический вызов в ``ImportService._register_actions``).
3. Через ``dispatch`` проверяем, что stub-handler возвращает метаданные
   импортированного endpoint'а — это и есть "endpoint вызывается".

Тест намеренно не использует production ``ActionHandlerRegistry`` —
его сигнатура keyword-only, и ``_register_actions`` вызывает его
позиционно (legacy-поведение, миграция к kw-only — отдельный долг).
Smoke-test покрывает фактический контур import → register → dispatch.
"""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

import pytest

from src.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.services.integrations import ImportService
from tests.integration.import_gateway.test_import_service import _FakeStore

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "import_gateway"


class _FakeActionRegistry:
    """Минимальный action-registry для smoke-теста.

    Совпадает по сигнатуре ``register(name, handler)`` с фактическим
    вызовом в ``ImportService._register_actions``. Поддерживает
    ``is_registered`` и ``dispatch``.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {}

    def register(
        self, action: str, handler: Callable[[dict[str, Any]], Awaitable[Any]]
    ) -> None:
        self._handlers[action] = handler

    def is_registered(self, action: str) -> bool:
        return action in self._handlers

    async def dispatch(self, action: str, payload: dict[str, Any]) -> Any:
        return await self._handlers[action](payload)


@pytest.mark.asyncio
async def test_imported_openapi_endpoint_is_registered_and_dispatchable() -> None:
    store = _FakeStore()
    registry = _FakeActionRegistry()
    svc = ImportService(connector_store=store, action_registry=registry)
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )

    result = await svc.import_and_register(src, register_actions=True)

    assert result["status"] == "imported"
    assert result["connector"] == "petstore"
    assert result["endpoints"] == 2

    expected = {"connector.petstore.listPets", "connector.petstore.createPet"}
    assert set(result["registered_actions"]) == expected
    for action in expected:
        assert registry.is_registered(action)

    response = await registry.dispatch("connector.petstore.listPets", {"limit": 10})
    assert response["status"] == "stub"
    assert response["operation_id"].endswith("listPets")
    assert response["method"].upper() == "GET"
    assert response["path"] == "/pets"
    assert response["payload"] == {"limit": 10}


@pytest.mark.asyncio
async def test_imported_endpoint_dispatch_handles_post_with_body() -> None:
    store = _FakeStore()
    registry = _FakeActionRegistry()
    svc = ImportService(connector_store=store, action_registry=registry)
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )
    await svc.import_and_register(src, register_actions=True)

    body = {"id": 1, "name": "Rex"}
    response = await registry.dispatch("connector.petstore.createPet", body)
    assert response["status"] == "stub"
    assert response["method"].upper() == "POST"
    assert response["path"] == "/pets"
    assert response["payload"] == body
