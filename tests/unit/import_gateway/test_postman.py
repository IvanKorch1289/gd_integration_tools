"""W24 — Postman backend тесты."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.backend.core.models.connector_spec import AuthSchemeKind
from src.backend.infrastructure.import_gateway.postman import PostmanImportGateway

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "import_gateway" / "postman"


@pytest.mark.asyncio
async def test_postman_minimal_collection_imports_one_endpoint() -> None:
    src = ImportSource(
        kind=ImportSourceKind.POSTMAN,
        content=(FIXTURES / "minimal.json").read_bytes(),
        prefix="pm",
    )
    spec = await PostmanImportGateway().import_spec(src)
    assert spec.name == "minimalcollection"
    assert spec.title == "MinimalCollection"
    assert len(spec.endpoints) == 1
    assert spec.endpoints[0].operation_id == "pm.get_user"
    assert spec.endpoints[0].method == "GET"
    assert spec.source_kind == "postman"
    assert spec.source_hash and len(spec.source_hash) == 64


@pytest.mark.asyncio
async def test_postman_nested_folders_get_dotted_prefix() -> None:
    src = ImportSource(
        kind=ImportSourceKind.POSTMAN,
        content=(FIXTURES / "nested_folders.json").read_bytes(),
        prefix="pm",
    )
    spec = await PostmanImportGateway().import_spec(src)
    op_ids = {ep.operation_id for ep in spec.endpoints}
    assert "pm.users.list_users" in op_ids
    assert "pm.users.admin.promote_user" in op_ids


@pytest.mark.asyncio
async def test_postman_bearer_auth_extracts_secret_ref() -> None:
    src = ImportSource(
        kind=ImportSourceKind.POSTMAN,
        content=(FIXTURES / "with_bearer_auth.json").read_bytes(),
        prefix="auth",
    )
    spec = await PostmanImportGateway().import_spec(src)
    assert spec.auth is not None
    assert spec.auth.kind is AuthSchemeKind.BEARER
    assert "token" in spec.auth.secret_refs
    # Сами значения секретов в spec не сохраняются — только SecretRef.
    assert spec.auth.secret_refs["token"].ref.startswith("${")


@pytest.mark.asyncio
async def test_postman_invalid_json_raises_import_error() -> None:
    src = ImportSource(
        kind=ImportSourceKind.POSTMAN, content=b"not-json", prefix="x"
    )
    with pytest.raises(ImportError):
        await PostmanImportGateway().import_spec(src)


@pytest.mark.asyncio
async def test_postman_collection_without_items_raises_value_error() -> None:
    src = ImportSource(
        kind=ImportSourceKind.POSTMAN,
        content=b'{"info":{"name":"Empty","schema":"...v2.1.0..."},"item":[]}',
        prefix="x",
    )
    with pytest.raises(ValueError):
        await PostmanImportGateway().import_spec(src)
