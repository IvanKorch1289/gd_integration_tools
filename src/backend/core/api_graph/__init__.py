"""OpenAPI Graph Importer (Wave 2 DX #56 — security + multi-endpoint).

Проблема (DEEP_AUDIT):
    Existing ``api_importer`` парсит OpenAPI в flat dataclasses, но:
    - НЕ строит schema dependency graph (ref → ref).
    - НЕ валидирует security schemes (deprecated API keys, missing scopes).
    - НЕ объединяет multiple OpenAPI файлов.
    - НЕ обнаруживает deprecated operations / removed endpoints.

Решение:
    ``OpenAPIGraph`` — расширенный importer:

    1. ``GraphNode`` — node в schema graph (schema name, path, operation).
    2. ``GraphEdge`` — ref dependency (schema→schema, op→schema).
    3. ``SecurityIssue`` — найденная security проблема.
    4. ``import_openapi_graph(spec)`` → ``OpenAPIGraph``.
    5. Security validator: missing schemes, deprecated fields.
    6. Multi-endpoint merge: ``merge_graphs(graphs)``.

Использование::

    from src.backend.core.api_graph import (  # noqa: F401 — re-export
        import_openapi_graph, OpenAPIGraph, validate_security,
    )

    graph = import_openapi_graph(openapi_spec)
    # Schema references.
    schema_refs = graph.schema_references("Order")
    # Endpoints using a schema.
    endpoints = graph.endpoints_using_schema("Order")
    # Security issues.
    issues = validate_security(graph)
"""

from __future__ import annotations

from src.backend.core.api_graph.graph import (  # noqa: F401 — re-export
    EndpointNode,
    GraphEdge,
    GraphNode,
    GraphNodeType,
    OpenAPIGraph,
    SecurityIssue,
    SecuritySeverity,
    import_openapi_graph,
    merge_graphs,
    validate_security,
)

__all__ = (
    "EndpointNode",
    "GraphEdge",
    "GraphNode",
    "GraphNodeType",
    "OpenAPIGraph",
    "SecurityIssue",
    "SecuritySeverity",
    "import_openapi_graph",
    "merge_graphs",
    "validate_security",
)
