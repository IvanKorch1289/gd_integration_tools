"""W24 — ImportService integration: idempotency + orphan cleanup + secret_refs."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.core.models.connector_configs import ConnectorConfigEntry
from src.services.integrations import ImportService

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "import_gateway"


class _FakeStore:
    """In-memory ConnectorConfigStore-like для тестов (без Mongo)."""

    def __init__(self) -> None:
        self._data: dict[str, ConnectorConfigEntry] = {}

    async def get(self, name: str) -> ConnectorConfigEntry | None:
        return self._data.get(name)

    async def save(
        self,
        name: str,
        config: dict[str, Any],
        *,
        enabled: bool = True,
        user: str | None = None,
    ) -> ConnectorConfigEntry:
        existing = self._data.get(name)
        version = (existing.version + 1) if existing else 1
        from datetime import datetime, timezone

        entry = ConnectorConfigEntry(
            name=name,
            config=dict(config),
            enabled=enabled,
            version=version,
            updated_at=datetime.now(timezone.utc),
            updated_by=user,
        )
        self._data[name] = entry
        return entry

    async def list_all(self) -> list[ConnectorConfigEntry]:
        return list(self._data.values())

    async def delete(self, name: str) -> bool:
        return self._data.pop(name, None) is not None

    async def ensure_indexes(self) -> None:
        return None


@pytest.mark.asyncio
async def test_import_service_imports_openapi_and_persists() -> None:
    store = _FakeStore()
    svc = ImportService(connector_store=store, action_registry=None)
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )
    result = await svc.import_and_register(src, register_actions=False)
    assert result["status"] == "imported"
    assert result["connector"] == "petstore"
    assert result["endpoints"] == 2
    assert result["version"] == 1
    saved = await store.get("petstore")
    assert saved is not None
    assert saved.config["source_kind"] == "openapi"


@pytest.mark.asyncio
async def test_import_service_idempotent_on_same_hash() -> None:
    """Повторный import того же spec → status=skipped без version-bump."""
    store = _FakeStore()
    svc = ImportService(connector_store=store, action_registry=None)
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )
    first = await svc.import_and_register(src, register_actions=False)
    second = await svc.import_and_register(src, register_actions=False)
    assert first["status"] == "imported"
    assert second["status"] == "skipped"
    assert second["reason"] == "spec_hash_unchanged"
    assert second["version"] == first["version"]


@pytest.mark.asyncio
async def test_import_service_force_overrides_idempotency() -> None:
    store = _FakeStore()
    svc = ImportService(connector_store=store, action_registry=None)
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )
    await svc.import_and_register(src, register_actions=False)
    forced = await svc.import_and_register(src, force=True, register_actions=False)
    assert forced["status"] == "updated"
    assert forced["version"] == 2


@pytest.mark.asyncio
async def test_import_service_secret_refs_required_for_bearer_openapi() -> None:
    store = _FakeStore()
    svc = ImportService(connector_store=store, action_registry=None)
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "with_security_bearer.yaml").read_bytes(),
        prefix="me",
    )
    result = await svc.import_and_register(src, register_actions=False)
    assert result["secret_refs_required"]
    assert any(r["key"] == "token" for r in result["secret_refs_required"])


@pytest.mark.asyncio
async def test_import_service_orphan_cleanup_after_endpoint_removal() -> None:
    """Эндпоинт исчез из обновлённого spec → попадает в removed_orphans."""
    store = _FakeStore()
    svc = ImportService(connector_store=store, action_registry=None)

    # Первый импорт — 2 endpoint'а
    src_v1 = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )
    await svc.import_and_register(src_v1, register_actions=False)

    # Второй импорт — модифицированный spec без createPet
    modified = (FIXTURES / "openapi" / "petstore_minimal.yaml").read_text()
    modified = modified.replace(
        "    post:\n      operationId: createPet\n      summary: Create pet\n      requestBody:\n        required: true\n        content:\n          application/json:\n            schema:\n              $ref: \"#/components/schemas/Pet\"\n      responses:\n        \"201\":\n          description: Created\n",
        "",
    )
    src_v2 = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=modified.encode(),
        prefix="petstore",
    )
    result = await svc.import_and_register(src_v2, force=True, register_actions=False)
    assert "petstore.createPet" in result["removed_orphans"]


@pytest.mark.asyncio
async def test_import_action_dsl_wrapper() -> None:
    """ImportService.import_action принимает DSL payload {kind, content, ...}."""
    store = _FakeStore()
    svc = ImportService(connector_store=store, action_registry=None)
    payload = {
        "kind": "openapi",
        "content": (FIXTURES / "openapi" / "petstore_minimal.yaml").read_bytes(),
        "prefix": "via_action",
        "dry_run": True,
    }
    result = await svc.import_action(payload)
    assert result["status"] == "imported"
    assert result["connector"] == "petstore"


@pytest.mark.asyncio
async def test_import_action_invalid_payload_raises() -> None:
    svc = ImportService(connector_store=_FakeStore(), action_registry=None)
    with pytest.raises(ValueError):
        await svc.import_action({"kind": "openapi"})  # нет content
