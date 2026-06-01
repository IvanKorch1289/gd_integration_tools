"""W24 — OpenAPI backend тесты."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.backend.core.models.connector_spec import AuthSchemeKind
from src.backend.infrastructure.import_gateway.openapi import OpenAPIImportGateway

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "import_gateway" / "openapi"


@pytest.mark.asyncio
async def test_openapi_30_petstore_minimal() -> None:
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "petstore_minimal.yaml").read_bytes(),
        prefix="petstore",
    )
    spec = await OpenAPIImportGateway().import_spec(src)
    assert spec.title == "PetStore"
    assert spec.base_url == "https://petstore.example.com/v1"
    op_ids = {ep.operation_id for ep in spec.endpoints}
    assert {"petstore.listPets", "petstore.createPet"} <= op_ids
    methods = {ep.method for ep in spec.endpoints}
    assert {"GET", "POST"} <= methods
    assert "Pet" in spec.schemas


@pytest.mark.asyncio
async def test_openapi_31_supports_modern_version() -> None:
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "openapi_31.yaml").read_bytes(),
        prefix="ev",
    )
    spec = await OpenAPIImportGateway().import_spec(src)
    assert len(spec.endpoints) == 1
    assert spec.metadata["openapi_version"].startswith("3.1")


@pytest.mark.asyncio
async def test_openapi_security_bearer_extracts_secret_ref() -> None:
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "with_security_bearer.yaml").read_bytes(),
        prefix="me",
    )
    spec = await OpenAPIImportGateway().import_spec(src)
    assert spec.auth is not None
    assert spec.auth.kind is AuthSchemeKind.BEARER
    assert "token" in spec.auth.secret_refs


@pytest.mark.asyncio
async def test_openapi_security_apikey_extracts_param_name() -> None:
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI,
        content=(FIXTURES / "with_apikey.yaml").read_bytes(),
        prefix="data",
    )
    spec = await OpenAPIImportGateway().import_spec(src)
    assert spec.auth is not None
    assert spec.auth.kind is AuthSchemeKind.API_KEY
    assert spec.auth.param_name == "X-API-Key"


@pytest.mark.asyncio
async def test_openapi_invalid_yaml_raises_import_error() -> None:
    src = ImportSource(
        kind=ImportSourceKind.OPENAPI, content=b"::not yaml or json::", prefix="x"
    )
    with pytest.raises((ImportError, ValueError)):
        await OpenAPIImportGateway().import_spec(src)
