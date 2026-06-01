"""W24/pre-W26 — smoke-test импорта OpenAPI и dispatch через action-registry.

Сценарий:
1. ``ImportService.import_and_register`` парсит ``petstore_minimal.yaml``.
2. Action'ы регистрируются в **production** ``ActionHandlerRegistry`` через
   kw-only API: ``service_method="dispatch_endpoint"`` (единая точка диспатча
   через :class:`ImportedActionService`).
3. Через ``ActionHandlerRegistry.dispatch`` проверяем, что stub возвращает
   метаданные импортированного endpoint'а — это и есть "endpoint вызывается".

Проверяет интеграцию с настоящей kw-only сигнатурой реестра, без fake-shim'ов.
"""

# ruff: noqa: S101

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from src.backend.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.backend.dsl.commands.action_registry import ActionHandlerRegistry
from src.backend.schemas.invocation import ActionCommandSchema
from src.backend.services.integrations import ImportService, get_imported_action_service
from tests.integration.import_gateway.test_import_service import _FakeStore

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "import_gateway"


@pytest.fixture(autouse=True)
def _reset_imported_action_catalog() -> Iterator[None]:
    """Гарантирует чистый ImportedActionService между тестами."""
    catalog = get_imported_action_service()
    catalog.clear()
    yield
    catalog.clear()


@pytest.mark.asyncio
async def test_imported_openapi_endpoint_is_registered_and_dispatchable() -> None:
    store = _FakeStore()
    registry = ActionHandlerRegistry()
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
        assert get_imported_action_service().is_registered(action)

    response = await registry.dispatch(
        ActionCommandSchema(
            action="connector.petstore.listPets",
            payload={"action": "connector.petstore.listPets", "limit": 10},
        )
    )
    assert response["status"] == "stub"
    assert response["operation_id"].endswith("listPets")
    assert response["method"].upper() == "GET"
    assert response["path"] == "/pets"
    assert response["payload"] == {"limit": 10}


@pytest.mark.asyncio
async def test_imported_endpoint_dispatch_handles_post_with_body() -> None:
    store = _FakeStore()
    registry = ActionHandlerRegistry()
    svc = ImportService(connector_store=store, action_registry=registry)
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )
    await svc.import_and_register(src, register_actions=True)

    body = {"id": 1, "name": "Rex"}
    response = await registry.dispatch(
        ActionCommandSchema(
            action="connector.petstore.createPet",
            payload={"action": "connector.petstore.createPet", **body},
        )
    )
    assert response["status"] == "stub"
    assert response["method"].upper() == "POST"
    assert response["path"] == "/pets"
    assert response["payload"] == body
