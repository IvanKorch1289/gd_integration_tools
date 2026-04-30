"""W24 — WSDL backend тесты (через zeep)."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.interfaces.import_gateway import ImportSource, ImportSourceKind
from src.infrastructure.import_gateway.wsdl import WsdlImportGateway

FIXTURES = Path(__file__).parent.parent.parent / "fixtures" / "import_gateway" / "wsdl"


@pytest.mark.asyncio
async def test_wsdl_simple_service_imports_one_operation() -> None:
    src = ImportSource(
        kind=ImportSourceKind.WSDL,
        content=(FIXTURES / "simple_service.wsdl").read_bytes(),
        prefix="hello",
    )
    spec = await WsdlImportGateway().import_spec(src)
    assert spec.metadata.get("transport") == "soap"
    assert len(spec.endpoints) == 1
    op = spec.endpoints[0]
    assert op.method == "SOAP"
    assert "sayHello" in op.operation_id
    assert spec.source_kind == "wsdl"


@pytest.mark.asyncio
async def test_wsdl_invalid_xml_raises() -> None:
    """Невалидный/неполный WSDL → ImportError или ValueError (зависит от того,
    отвалится ли zeep на парсинге или мы сами бросим на отсутствии <service>)."""
    src = ImportSource(
        kind=ImportSourceKind.WSDL, content=b"<not-wsdl>broken</not-wsdl>", prefix="x"
    )
    with pytest.raises((ImportError, ValueError)):
        await WsdlImportGateway().import_spec(src)


@pytest.mark.asyncio
async def test_wsdl_includes_service_in_tags() -> None:
    src = ImportSource(
        kind=ImportSourceKind.WSDL,
        content=(FIXTURES / "simple_service.wsdl").read_bytes(),
        prefix="hello",
    )
    spec = await WsdlImportGateway().import_spec(src)
    op = spec.endpoints[0]
    assert "HelloService" in op.tags
