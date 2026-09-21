"""Focused tests for ``core.api_importer`` (Wave 2 DX)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.core.api_importer import (
    APIImporter,
    ImportedAPI,
    OperationInfo,
    PathInfo,
    export_route_draft,
    generate_connector_draft,
    generate_route_draft,
    import_openapi,
    import_swagger,
)

SAMPLE_OPENAPI = {
    "openapi": "3.0.0",
    "info": {
        "title": "Partner Orders API",
        "version": "1.2.3",
        "description": "API for managing partner orders",
    },
    "servers": [{"url": "https://api.partner.com/v1"}],
    "paths": {
        "/orders": {
            "get": {
                "operationId": "listOrders",
                "summary": "List orders",
                "tags": ["orders"],
                "parameters": [
                    {"name": "status", "in": "query", "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "OK"}},
            },
            "post": {
                "operationId": "createOrder",
                "summary": "Create order",
                "tags": ["orders"],
                "requestBody": {
                    "content": {"application/json": {"schema": {"type": "object"}}}
                },
                "responses": {"201": {"description": "Created"}},
            },
        },
        "/orders/{id}": {
            "get": {
                "operationId": "getOrder",
                "summary": "Get order by ID",
                "responses": {"200": {"description": "OK"}},
            }
        },
    },
    "components": {
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer"},
            "apiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
        }
    },
}


SAMPLE_SWAGGER = {
    "swagger": "2.0",
    "info": {"title": "Legacy API", "version": "0.1.0"},
    "host": "api.legacy.com",
    "basePath": "/v1",
    "schemes": ["https"],
    "paths": {
        "/users": {
            "get": {
                "operationId": "getUsers",
                "summary": "Get users",
                "responses": {"200": {"description": "OK"}},
            }
        }
    },
}


class TestImportOpenAPI:
    def test_basic(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        assert api.title == "Partner Orders API"
        assert api.version == "1.2.3"
        assert api.source_format == "openapi3"
        assert len(api.paths) == 2

    def test_operation_count(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        assert api.operation_count() == 3  # GET /orders, POST /orders, GET /orders/{id}

    def test_servers(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        assert api.servers == [{"url": "https://api.partner.com/v1"}]

    def test_components(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        assert "securitySchemes" in api.components


class TestImportOpenAPIPaths:
    def test_path_info(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        # First path: /orders with 2 operations.
        first = api.paths[0]
        assert first.path == "/orders"
        assert len(first.operations) == 2
        methods = [op.method for op in first.operations]
        assert "GET" in methods
        assert "POST" in methods

    def test_operation_id(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        all_ops = [op for path in api.paths for op in path.operations]
        ids = [op.operation_id for op in all_ops]
        assert "listOrders" in ids
        assert "createOrder" in ids
        assert "getOrder" in ids

    def test_operation_summary(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        list_op = next(
            op
            for path in api.paths
            for op in path.operations
            if op.operation_id == "listOrders"
        )
        assert list_op.summary == "List orders"

    def test_operation_parameters(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        list_op = next(
            op
            for path in api.paths
            for op in path.operations
            if op.operation_id == "listOrders"
        )
        assert len(list_op.parameters) == 1
        assert list_op.parameters[0]["name"] == "status"

    def test_operation_request_body(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        create_op = next(
            op
            for path in api.paths
            for op in path.operations
            if op.operation_id == "createOrder"
        )
        assert "content" in create_op.request_body

    def test_empty_paths(self) -> None:
        api = import_openapi(
            {"info": {"title": "Empty", "version": "1.0"}, "paths": {}}
        )
        assert len(api.paths) == 0
        assert api.operation_count() == 0


class TestImportSwagger:
    def test_basic(self) -> None:
        api = import_swagger(SAMPLE_SWAGGER)
        assert api.title == "Legacy API"
        assert api.source_format == "swagger2"
        assert len(api.paths) == 1

    def test_servers(self) -> None:
        api = import_swagger(SAMPLE_SWAGGER)
        assert api.servers == [{"url": "https://api.legacy.com/v1"}]

    def test_operation_id(self) -> None:
        api = import_swagger(SAMPLE_SWAGGER)
        op = api.paths[0].operations[0]
        assert op.operation_id == "getUsers"


class TestOperationInfo:
    def test_init(self) -> None:
        op = OperationInfo(method="GET", path="/x")
        assert op.operation_id == ""
        assert op.parameters == []


class TestPathInfo:
    def test_init(self) -> None:
        p = PathInfo(path="/x")
        assert p.operations == []


class TestImportedAPI:
    def test_defaults(self) -> None:
        api = ImportedAPI()
        assert api.title == ""
        assert api.operation_count() == 0


class TestGenerateConnectorDraft:
    def test_basic(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        draft = generate_connector_draft(api, name="partner_orders")
        assert draft.name == "partner_orders"
        assert draft.version == "1.2.3"
        assert draft.base_url == "https://api.partner.com/v1"
        assert len(draft.operations) == 3
        assert "bearerAuth(http)" in draft.auth_schemes
        assert "apiKeyAuth(apiKey)" in draft.auth_schemes

    def test_operation_dict(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        draft = generate_connector_draft(api)
        op = draft.operations[0]
        assert "name" in op
        assert "method" in op
        assert "path" in op
        assert op["method"] == "GET"
        assert op["path"] == "/orders"

    def test_schemas(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        draft = generate_connector_draft(api)
        assert "securitySchemes" in draft.schemas


class TestGenerateRouteDraft:
    def test_basic(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        files = generate_route_draft(api, route_id="partner-orders")
        assert "route.toml" in files
        assert "test_partner-orders.py" in files

    def test_route_toml_content(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        files = generate_route_draft(api, route_id="r1")
        toml = files["route.toml"]
        assert "[route]" in toml
        assert 'id = "r1"' in toml
        assert "[contract]" in toml
        assert "timeout_seconds" in toml
        assert "idempotency_key_field" in toml
        assert "dlq_topic" in toml

    def test_test_scaffold_content(self) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        files = generate_route_draft(api, route_id="r1")
        test = files["test_r1.py"]
        assert "ContractTestCase" in test
        assert "ContractTestHarness" in test


class TestExportRouteDraft:
    def test_export(self, tmp_path: Path) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        files = generate_route_draft(api, route_id="r1")
        written = export_route_draft(files, tmp_path / "extensions" / "r1")
        assert len(written) == 2
        # Files exist.
        assert (tmp_path / "extensions" / "r1" / "route.toml").exists()
        assert (tmp_path / "extensions" / "r1" / "test_r1.py").exists()

    def test_export_creates_nested_dirs(self, tmp_path: Path) -> None:
        api = import_openapi(SAMPLE_OPENAPI)
        # Subdirectory: route_id + suffix makes it path-like.
        files = generate_route_draft(api, route_id="nested-r1")
        target = tmp_path / "extensions" / "nested-r1"
        export_route_draft(files, target)
        assert (target / "route.toml").exists()
        assert (target / "test_nested-r1.py").exists()


class TestAPIImporterFacade:
    def test_import_from_dict_openapi(self) -> None:
        api = APIImporter().import_from_dict(SAMPLE_OPENAPI)
        assert api.source_format == "openapi3"

    def test_import_from_dict_swagger(self) -> None:
        api = APIImporter().import_from_dict(SAMPLE_SWAGGER)
        assert api.source_format == "swagger2"

    def test_import_from_file(self, tmp_path: Path) -> None:
        spec_file = tmp_path / "openapi.json"
        spec_file.write_text(
            '{"openapi": "3.0.0", "info": {"title": "t", "version": "1"}}',
            encoding="utf-8",
        )
        api = APIImporter().import_from_file(spec_file)
        assert api.title == "t"

    def test_unknown_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown spec format"):
            APIImporter().import_from_dict({"info": {}})


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import api_importer

        assert len(api_importer.__all__) == 10


class TestRealisticExample:
    """Realistic: import petstore-style API → generate route + tests."""

    def test_petstore_workflow(self, tmp_path: Path) -> None:
        petstore = {
            "openapi": "3.0.0",
            "info": {
                "title": "Petstore",
                "version": "1.0.0",
                "description": "Pet management API",
            },
            "servers": [{"url": "https://petstore.example.com/v1"}],
            "paths": {
                "/pets": {
                    "get": {
                        "operationId": "listPets",
                        "summary": "List all pets",
                        "responses": {"200": {"description": "OK"}},
                    },
                    "post": {
                        "operationId": "createPet",
                        "summary": "Create a pet",
                        "requestBody": {
                            "content": {
                                "application/json": {"schema": {"type": "object"}}
                            }
                        },
                        "responses": {"201": {"description": "Created"}},
                    },
                },
                "/pets/{id}": {
                    "get": {
                        "operationId": "getPet",
                        "summary": "Get pet by ID",
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
        }
        # 1. Import.
        api = import_openapi(petstore)
        assert api.operation_count() == 3

        # 2. Generate connector draft.
        connector = generate_connector_draft(api, name="petstore")
        assert (
            connector.operation_count() == 3
            if hasattr(connector, "operation_count")
            else True
        )
        assert len(connector.operations) == 3

        # 3. Generate route draft.
        files = generate_route_draft(api, route_id="petstore-sync")
        assert "route.toml" in files
        assert "test_petstore-sync.py" in files

        # 4. Export to disk.
        target = tmp_path / "extensions" / "petstore"
        export_route_draft(files, target)
        assert (target / "route.toml").exists()
        assert (target / "test_petstore-sync.py").exists()
        # Verify content.
        toml = (target / "route.toml").read_text()
        assert "petstore-sync" in toml
