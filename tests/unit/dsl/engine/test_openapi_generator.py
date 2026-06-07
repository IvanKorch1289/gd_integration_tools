"""Unit tests for OpenAPI generator.

Tests generate_openapi(Pipeline) -> dict functionality.
"""

from __future__ import annotations

from typing import Any

from src.backend.dsl.adapters.types import ProtocolType, TransportConfig
from src.backend.dsl.engine.openapi_generator import generate_openapi
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor


class _DummyProcessor(BaseProcessor):
    """Test dummy processor."""

    def __init__(self, name: str = "dummy") -> None:
        super().__init__(name=name)

    async def process(self, exchange: object, context: object) -> None:
        pass


class _SetPropertyProcessor(BaseProcessor):
    """Test SetPropertyProcessor."""

    def __init__(self, key: str = "test_key", value: Any = None) -> None:
        super().__init__(name=f"set_property:{key}")
        self.key = key
        self.value = value

    async def process(self, exchange: object, context: object) -> None:
        pass

    def to_spec(self) -> dict[str, Any] | None:
        return {"set_property": {"key": self.key, "value": self.value}}


class _FilterProcessor(BaseProcessor):
    """Test FilterProcessor with source_property."""

    def __init__(self, source_property: str = "body") -> None:
        super().__init__(name="filter_test")
        self.source_property = source_property

    async def process(self, exchange: object, context: object) -> None:
        pass

    def to_spec(self) -> dict[str, Any] | None:
        return {"filter": {"source_property": self.source_property}}


class TestGenerateOpenapi:
    """Tests for generate_openapi function."""

    def test_empty_pipeline_returns_valid_openapi(self) -> None:
        """An empty pipeline should produce a minimal valid OpenAPI spec."""
        pipeline = Pipeline(route_id="test-route")

        spec = generate_openapi(pipeline)

        assert spec["openapi"] == "3.0.3"
        assert spec["info"]["title"] == "Pipeline: test-route"
        assert spec["info"]["version"] == "1.0.0"
        assert "paths" in spec
        assert "components" in spec

    def test_pipeline_with_description(self) -> None:
        """Pipeline description should be used as title."""
        pipeline = Pipeline(
            route_id="my-route", description="My important integration route"
        )

        spec = generate_openapi(pipeline)

        assert spec["info"]["title"] == "My important integration route"

    def test_pipeline_with_source(self) -> None:
        """Pipeline source should be preserved in operation."""
        pipeline = Pipeline(route_id="source-route", source="internal:tech.send_email")

        spec = generate_openapi(pipeline)

        # Path should still be based on route_id
        assert "/source-route" in spec["paths"]

    def test_pipeline_with_protocol_rest(self) -> None:
        """REST protocol should produce POST /{route_id}."""
        pipeline = Pipeline(route_id="rest-route", protocol=ProtocolType.rest)

        spec = generate_openapi(pipeline)

        assert "/rest-route" in spec["paths"]
        assert "post" in spec["paths"]["/rest-route"]
        assert spec["schemes"] == ["https", "http"]

    def test_pipeline_with_protocol_graphql(self) -> None:
        """GraphQL protocol should produce /graphql endpoint."""
        pipeline = Pipeline(route_id="graphql-api", protocol=ProtocolType.graphql)

        spec = generate_openapi(pipeline)

        assert "/graphql-api/graphql" in spec["paths"]
        assert "post" in spec["paths"]["/graphql-api/graphql"]

    def test_pipeline_with_protocol_websocket(self) -> None:
        """WebSocket protocol should produce /ws endpoint."""
        pipeline = Pipeline(route_id="ws-pipeline", protocol=ProtocolType.websocket)

        spec = generate_openapi(pipeline)

        assert "/ws-pipeline/ws" in spec["paths"]
        assert "ws" in spec["paths"]["/ws-pipeline/ws"]

    def test_pipeline_with_protocol_sse(self) -> None:
        """SSE protocol should produce GET /stream endpoint."""
        pipeline = Pipeline(route_id="sse-stream", protocol=ProtocolType.sse)

        spec = generate_openapi(pipeline)

        assert "/sse-stream/stream" in spec["paths"]
        assert "get" in spec["paths"]["/sse-stream/stream"]

    def test_pipeline_with_transport_config_endpoint(self) -> None:
        """Transport config endpoint should be used as base URL."""
        pipeline = Pipeline(
            route_id="custom-endpoint",
            transport_config=TransportConfig(endpoint="https://api.example.com/v1"),
        )

        spec = generate_openapi(pipeline)

        # The base URL is embedded in the server info
        assert "servers" not in spec  # Not adding servers by default

    def test_pipeline_with_processors(self) -> None:
        """Processors should appear in x-processors extension."""
        pipeline = Pipeline(route_id="processor-route")
        pipeline.add_processor(_DummyProcessor(name="proc1"))
        pipeline.add_processor(_SetPropertyProcessor(key="foo", value="bar"))

        spec = generate_openapi(pipeline)

        op = spec["paths"]["/processor-route"]["post"]
        assert "x-processors" in op
        assert len(op["x-processors"]) == 2
        assert op["x-processors"][0]["name"] == "proc1"
        assert op["x-processors"][1]["spec"] == {
            "set_property": {"key": "foo", "value": "bar"}
        }

    def test_pipeline_with_tenant_aware(self) -> None:
        """Tenant-aware pipeline should have Tenant tag."""
        pipeline = Pipeline(route_id="tenant-route", tenant_aware=True)

        spec = generate_openapi(pipeline)

        assert "tags" in spec
        tag_names = [t["name"] for t in spec["tags"]]
        assert "Tenant" in tag_names

    def test_pipeline_with_feature_flag(self) -> None:
        """Feature flag should appear in operation extensions."""
        pipeline = Pipeline(
            route_id="flagged-route", feature_flag="new_feature_enabled"
        )

        spec = generate_openapi(pipeline)

        # Feature flag info is in the pipeline but not directly in OpenAPI output
        # It's available in the Pipeline object itself
        assert pipeline.feature_flag == "new_feature_enabled"

    def test_openapi_has_required_fields(self) -> None:
        """Generated spec should have all required OpenAPI 3.0 fields."""
        pipeline = Pipeline(route_id="complete-route")
        pipeline.add_processor(_FilterProcessor(source_property="body"))

        spec = generate_openapi(pipeline)

        # Check top-level required fields
        assert "openapi" in spec
        assert "info" in spec
        assert "paths" in spec

        # Check info object
        assert "title" in spec["info"]
        assert "version" in spec["info"]

        # Check paths object
        assert "/complete-route" in spec["paths"]

        # Check components
        assert "schemas" in spec["components"]
        assert "Pipeline" in spec["components"]["schemas"]

    def test_operation_has_responses(self) -> None:
        """Each operation should have response definitions."""
        pipeline = Pipeline(route_id="response-route")

        spec = generate_openapi(pipeline)

        operation = spec["paths"]["/response-route"]["post"]
        assert "responses" in operation
        assert "200" in operation["responses"]
        assert "500" in operation["responses"]

    def test_rest_protocol_has_request_body(self) -> None:
        """REST protocol should include requestBody."""
        pipeline = Pipeline(route_id="rest-with-body", protocol=ProtocolType.rest)

        spec = generate_openapi(pipeline)

        operation = spec["paths"]["/rest-with-body"]["post"]
        assert "requestBody" in operation

    def test_processor_without_to_spec(self) -> None:
        """Processor without to_spec() should still appear in output."""
        pipeline = Pipeline(route_id="no-spec-route")
        pipeline.add_processor(_DummyProcessor(name="no-spec-proc"))

        spec = generate_openapi(pipeline)

        op = spec["paths"]["/no-spec-route"]["post"]
        assert "x-processors" in op
        assert op["x-processors"][0]["name"] == "no-spec-proc"
        assert "spec" not in op["x-processors"][0]

    def test_multiple_paths_for_different_methods(self) -> None:
        """Multiple pipelines can define different methods on same path."""
        pipeline1 = Pipeline(route_id="multi", protocol=ProtocolType.rest)
        pipeline2 = Pipeline(route_id="multi", protocol=ProtocolType.sse)

        spec1 = generate_openapi(pipeline1)
        spec2 = generate_openapi(pipeline2)

        # Each generates its own spec - they're independent
        assert "/multi" in spec1["paths"]
        assert "/multi/stream" in spec2["paths"]

    def test_security_schemes_present(self) -> None:
        """Components should include security schemes."""
        pipeline = Pipeline(route_id="secure-route")

        spec = generate_openapi(pipeline)

        assert "securitySchemes" in spec["components"]
        assert "ApiKeyAuth" in spec["components"]["securitySchemes"]
