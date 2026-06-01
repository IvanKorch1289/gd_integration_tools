"""OpenAPI schema generator for DSL Pipelines.

Generates OpenAPI 3.0 specifications from Pipeline objects,
extracting endpoints, processors, and transport configurations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.engine.pipeline import Pipeline

__all__ = ("generate_openapi",)


def generate_openapi(pipeline: Pipeline) -> dict[str, Any]:
    """Generate an OpenAPI 3.0 specification from a Pipeline.

    Args:
        pipeline: The DSL pipeline to generate OpenAPI spec for.

    Returns:
        A dictionary representing a valid OpenAPI 3.0 specification.

    Example:
        >>> from src.backend.dsl.engine.pipeline import Pipeline
        >>> spec = generate_openapi(pipeline)
        >>> spec["openapi"]
        '3.0.3'
    """
    from src.backend.dsl.adapters.types import ProtocolType

    route_id = pipeline.route_id
    base_url = _extract_base_url(pipeline)

    spec: dict[str, Any] = {
        "openapi": "3.0.3",
        "info": {
            "title": pipeline.description or f"Pipeline: {route_id}",
            "version": "1.0.0",
        },
        "paths": _build_paths(pipeline, base_url),
    }

    if pipeline.protocol is not None:
        spec["schemes"] = _get_schemes(pipeline.protocol)

    # Components section for reusable schemas
    spec["components"] = {
        "schemas": _build_components_schemas(pipeline),
        "securitySchemes": _build_security_schemes(pipeline),
    }

    # Tags for organizing operations
    tags = _build_tags(pipeline)
    if tags:
        spec["tags"] = tags

    return spec


def _extract_base_url(pipeline: Pipeline) -> str:
    """Extract base URL from pipeline transport config."""
    if pipeline.transport_config and pipeline.transport_config.endpoint:
        return pipeline.transport_config.endpoint
    return "http://localhost"


def _build_paths(pipeline: Pipeline, base_url: str) -> dict[str, Any]:
    """Build the paths section of the OpenAPI spec."""
    paths: dict[str, Any] = {}

    if pipeline.protocol is None:
        protocol = ProtocolType.rest
    else:
        protocol = pipeline.protocol

    # Determine HTTP method and path from source or protocol
    path, method = _infer_path_and_method(pipeline, protocol)

    if path not in paths:
        paths[path] = {}

    paths[path][method] = _build_operation(pipeline)

    return paths


def _infer_path_and_method(
    pipeline: Pipeline, protocol: ProtocolType
) -> tuple[str, str]:
    """Infer the API path and HTTP method from pipeline configuration."""
    # Default to /{route_id} with POST for REST
    if protocol == ProtocolType.rest:
        return f"/{pipeline.route_id}", "post"
    elif protocol == ProtocolType.graphql:
        return f"/{pipeline.route_id}/graphql", "post"
    elif protocol == ProtocolType.websocket:
        return f"/{pipeline.route_id}/ws", "ws"
    elif protocol == ProtocolType.sse:
        return f"/{pipeline.route_id}/stream", "get"
    elif protocol == ProtocolType.grpc:
        return f"/{pipeline.route_id}", "post"
    else:
        return f"/{pipeline.route_id}", "post"


def _build_operation(pipeline: Pipeline) -> dict[str, Any]:
    """Build a single OpenAPI operation."""
    operation: dict[str, Any] = {
        "summary": pipeline.description or f"Pipeline: {pipeline.route_id}",
        "operationId": pipeline.route_id,
        "responses": _build_responses(pipeline),
    }

    # Add request body info for REST
    if pipeline.protocol in (ProtocolType.rest, ProtocolType.graphql, None):
        operation["requestBody"] = _build_request_body(pipeline)

    # Add processors as extensions
    if pipeline.processors:
        operation["x-processors"] = [_processor_to_dict(p) for p in pipeline.processors]

    return operation


def _build_responses(pipeline: Pipeline) -> dict[str, Any]:
    """Build the responses section."""
    return {
        "200": {
            "description": "Successful response",
            "content": {"application/json": {"schema": {"type": "object"}}},
        },
        "500": {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {"error": {"type": "string"}},
                    }
                }
            },
        },
    }


def _build_request_body(pipeline: Pipeline) -> dict[str, Any]:
    """Build the request body specification."""
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "route_id": {"type": "string", "example": pipeline.route_id},
                        "body": {
                            "type": "object",
                            "description": "Pipeline input body",
                        },
                    },
                }
            }
        },
    }


def _build_components_schemas(pipeline: Pipeline) -> dict[str, Any]:
    """Build reusable schemas in components section."""
    schemas: dict[str, Any] = {
        "Pipeline": {
            "type": "object",
            "properties": {
                "route_id": {"type": "string"},
                "source": {"type": "string"},
                "description": {"type": "string"},
                "protocol": {"type": "string"},
                "processors": {"type": "array", "items": {"type": "object"}},
            },
        }
    }

    # Add processor-specific schemas
    for proc in pipeline.processors:
        spec = proc.to_spec()
        if spec:
            proc_name = next(iter(spec.keys()), proc.name)
            schemas[proc_name] = {
                "type": "object",
                "properties": spec.get(proc_name, {}),
            }

    return schemas


def _build_security_schemes(pipeline: Pipeline) -> dict[str, Any]:
    """Build security schemes (placeholder - extend as needed)."""
    return {"ApiKeyAuth": {"type": "apiKey", "in": "header", "name": "X-API-Key"}}


def _build_tags(pipeline: Pipeline) -> list[dict[str, str]]:
    """Build tags for grouping operations."""
    tags = []

    if pipeline.protocol:
        tags.append(
            {
                "name": pipeline.protocol.value.upper(),
                "description": f"Operations via {pipeline.protocol.value} protocol",
            }
        )

    if pipeline.tenant_aware:
        tags.append({"name": "Tenant", "description": "Tenant-aware operations"})

    return tags


def _get_schemes(protocol: ProtocolType) -> list[str]:
    """Get OpenAPI scheme list based on protocol."""
    schemes_map = {
        ProtocolType.rest: ["https", "http"],
        ProtocolType.grpc: ["https"],
        ProtocolType.websocket: ["wss", "ws"],
        ProtocolType.graphql: ["https", "http"],
    }
    return schemes_map.get(protocol, ["https", "http"])


def _processor_to_dict(processor: Any) -> dict[str, Any]:
    """Convert a processor to a dictionary representation."""
    result: dict[str, Any] = {"name": processor.name}

    if hasattr(processor, "to_spec") and callable(processor.to_spec):
        spec = processor.to_spec()
        if spec:
            result["spec"] = spec

    return result
