"""Unit tests for src.backend.core.interfaces.import_gateway."""

from __future__ import annotations

from src.backend.core.interfaces.import_gateway import (
    ImportGateway,
    ImportSource,
    ImportSourceKind,
)


class TestImportSourceKind:
    def test_values(self) -> None:
        assert ImportSourceKind.POSTMAN == "postman"
        assert ImportSourceKind.OPENAPI == "openapi"
        assert ImportSourceKind.WSDL == "wsdl"


class TestImportSource:
    def test_defaults(self) -> None:
        src = ImportSource(kind=ImportSourceKind.OPENAPI, content="{}")
        assert src.source_url is None
        assert src.prefix == "ext"
        assert src.metadata == {}

    def test_full(self) -> None:
        src = ImportSource(
            kind=ImportSourceKind.POSTMAN,
            content=b"bytes",
            source_url="http://example.com",
            prefix="api",
            metadata={"batch": "1"},
        )
        assert src.prefix == "api"
        assert src.metadata == {"batch": "1"}


class TestImportGateway:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            kind: ImportSourceKind = ImportSourceKind.OPENAPI

            async def import_spec(self, source: ImportSource) -> object:
                return object()

        assert isinstance(Fake(), ImportGateway)

    def test_missing_method_fails(self) -> None:
        class Bad:
            kind: ImportSourceKind = ImportSourceKind.OPENAPI

        assert not isinstance(Bad(), ImportGateway)
