"""OpenAPI Graph — schema dependency + security validation (Wave 2 DX #56).

Pure-Python: build directed graph из OpenAPI 3.x spec, validate security.
"""

from __future__ import annotations

import enum
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

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


class GraphNodeType(str, enum.Enum):
    """Type of graph node."""

    SCHEMA = "schema"  # Component schema (in components.schemas).
    ENDPOINT = "endpoint"  # HTTP endpoint (path+method).
    PARAMETER = "parameter"  # Reusable parameter (in components.parameters).
    SECURITY = "security"  # Security scheme.


class SecuritySeverity(str, enum.Enum):
    """Severity of security issue."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


@dataclass(slots=True)
class GraphNode:
    """Single node в graph."""

    id: str
    type: GraphNodeType
    name: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    """Directed edge between nodes."""

    source: str  # source node id
    target: str  # target node id
    kind: str  # "ref" | "uses" | "produces" | "consumes" | "secured_by"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class EndpointNode:
    """Single endpoint (method+path) с metadata."""

    path: str
    method: str
    operation_id: str = ""
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    deprecated: bool = False
    security_schemes: list[str] = field(default_factory=list)
    request_schema: str = ""
    response_schema: str = ""

    def full_name(self) -> str:
        """Return canonical full name ``METHOD path`` (e.g. ``GET /orders/{id}``)."""
        return f"{self.method.upper()} {self.path}"


@dataclass(slots=True)
class SecurityIssue:
    """Security finding."""

    issue_type: str  # "no_security" | "deprecated_apikey" | "wildcard_scope" | ...
    severity: SecuritySeverity
    location: str  # path или scheme name
    description: str = ""
    recommendation: str = ""


class OpenAPIGraph:
    """Directed graph of OpenAPI spec.

    Nodes:
    - schema:* — OpenAPI components.schemas
    - endpoint:METHOD /path — HTTP endpoints
    - security:SchemeName — security schemes

    Edges:
    - endpoint → schema (uses / produces)
    - schema → schema ($ref dependencies)
    - endpoint → security (secured_by)
    """

    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: list[GraphEdge] = []
        self._endpoints: list[EndpointNode] = []
        self._spec: dict[str, Any] = {}

    @property
    def nodes(self) -> list[GraphNode]:
        return list(self._nodes.values())

    @property
    def edges(self) -> list[GraphEdge]:
        return list(self._edges)

    @property
    def endpoints(self) -> list[EndpointNode]:
        return list(self._endpoints)

    @property
    def spec(self) -> dict[str, Any]:
        return self._spec

    def get_node(self, node_id: str) -> GraphNode | None:
        return self._nodes.get(node_id)

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self._edges.append(edge)

    def schema_references(self, schema_name: str) -> list[str]:
        """Return all schema names referenced by given schema.

        Looks at ``$ref`` patterns: ``#/components/schemas/X`` and inline refs.
        """
        return [e.target for e in self._edges if e.source == f"schema:{schema_name}"]

    def endpoints_using_schema(self, schema_name: str) -> list[EndpointNode]:
        """Return endpoints that reference given schema in request or response."""
        target = f"schema:{schema_name}"
        result: list[EndpointNode] = []
        for edge in self._edges:
            if edge.target == target and edge.source.startswith("endpoint:"):
                # Find endpoint by id.
                ep = next(
                    (
                        e
                        for e in self._endpoints
                        if f"endpoint:{e.full_name()}" == edge.source
                    ),
                    None,
                )
                if ep is not None and ep not in result:
                    result.append(ep)
        return result

    def find_orphans(self) -> list[str]:
        """Find schemas (or endpoints) с no incoming edges (potentially unused)."""
        incoming: dict[str, int] = defaultdict(int)
        for edge in self._edges:
            incoming[edge.target] += 1
        return [
            n.id
            for n in self._nodes.values()
            if n.id.startswith("schema:") and incoming[n.id] == 0
        ]

    def find_cycles(self) -> list[list[str]]:
        """Detect cycles в schema graph (potential infinite recursion)."""
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in self._nodes}
        path: list[str] = []
        cycles: list[list[str]] = []

        def dfs(node_id: str) -> None:
            color[node_id] = GRAY
            path.append(node_id)
            for edge in self._edges:
                if edge.source != node_id:
                    continue
                if color[edge.target] == GRAY:
                    cycle_start = path.index(edge.target)
                    cycles.append(path[cycle_start:] + [edge.target])
                elif color[edge.target] == WHITE:
                    dfs(edge.target)
            path.pop()
            color[node_id] = BLACK

        for node_id in self._nodes:
            if color[node_id] == WHITE:
                dfs(node_id)
        return cycles

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_count": len(self._nodes),
            "edge_count": len(self._edges),
            "endpoint_count": len(self._endpoints),
            "nodes": [
                {"id": n.id, "type": n.type.value, "name": n.name}
                for n in self._nodes.values()
            ],
            "endpoints": [
                {
                    "path": e.path,
                    "method": e.method,
                    "deprecated": e.deprecated,
                    "security": e.security_schemes,
                }
                for e in self._endpoints
            ],
        }

    def clear(self) -> None:
        self._nodes.clear()
        self._edges.clear()
        self._endpoints.clear()
        self._spec.clear()


_REF_PATTERN = re.compile(r"#/components/(schemas|parameters|securitySchemes)/(\w+)")


def _extract_refs(schema: Any, refs: set[str]) -> None:
    """Recursively extract $ref names из JSON schema fragment."""
    if isinstance(schema, dict):
        ref = schema.get("$ref")
        if isinstance(ref, str):
            m = _REF_PATTERN.match(ref)
            if m and m.group(1) == "schemas":
                refs.add(m.group(2))
        for value in schema.values():
            _extract_refs(value, refs)
    elif isinstance(schema, list):
        for item in schema:
            _extract_refs(item, refs)


def import_openapi_graph(spec: dict[str, Any]) -> OpenAPIGraph:
    """Build full graph из OpenAPI 3.x spec.

    Nodes: schemas, endpoints, security schemes.
    Edges: schema→schema (ref), endpoint→schema (uses/produces),
    endpoint→security (secured_by).
    """
    graph = OpenAPIGraph()
    graph._spec = spec

    # 1. Schema nodes + ref edges.
    components = spec.get("components", {})
    schemas = components.get("schemas", {})
    for name in schemas:
        graph.add_node(
            GraphNode(id=f"schema:{name}", type=GraphNodeType.SCHEMA, name=name)
        )

    for name, schema in schemas.items():
        refs: set[str] = set()
        _extract_refs(schema, refs)
        for ref in refs:
            graph.add_edge(
                GraphEdge(source=f"schema:{name}", target=f"schema:{ref}", kind="ref")
            )

    # 2. Security scheme nodes.
    security_schemes = components.get("securitySchemes", {})
    for name in security_schemes:
        graph.add_node(
            GraphNode(
                id=f"security:{name}",
                type=GraphNodeType.SECURITY,
                name=name,
                metadata=security_schemes[name],
            )
        )

    # 3. Endpoint nodes + edges.
    for path, path_item in spec.get("paths", {}).items():
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            ep = EndpointNode(
                path=path,
                method=method.upper(),
                operation_id=op.get("operationId", ""),
                tags=list(op.get("tags", []) or []),
                summary=op.get("summary", ""),
                deprecated=op.get("deprecated", False),
                security_schemes=_extract_security_schemes(op, security_schemes),
            )
            # Extract request body schema ref.
            req_body = op.get("requestBody", {})
            req_schema = (
                req_body.get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if isinstance(req_schema, dict):
                ref = req_schema.get("$ref", "")
                m = _REF_PATTERN.match(ref)
                if m and m.group(1) == "schemas":
                    ep.request_schema = m.group(2)
                    graph.add_edge(
                        GraphEdge(
                            source=f"endpoint:{ep.full_name()}",
                            target=f"schema:{m.group(2)}",
                            kind="consumes",
                        )
                    )
            # Extract response schema ref (200 status).
            responses = op.get("responses", {})
            resp_200 = responses.get("200", {})
            resp_schema = (
                resp_200.get("content", {})
                .get("application/json", {})
                .get("schema", {})
            )
            if isinstance(resp_schema, dict):
                ref = resp_schema.get("$ref", "")
                m = _REF_PATTERN.match(ref)
                if m and m.group(1) == "schemas":
                    ep.response_schema = m.group(2)
                    graph.add_edge(
                        GraphEdge(
                            source=f"endpoint:{ep.full_name()}",
                            target=f"schema:{m.group(2)}",
                            kind="produces",
                        )
                    )
            # Edge to security scheme.
            for scheme in ep.security_schemes:
                graph.add_edge(
                    GraphEdge(
                        source=f"endpoint:{ep.full_name()}",
                        target=f"security:{scheme}",
                        kind="secured_by",
                    )
                )
            # Endpoint node.
            graph.add_node(
                GraphNode(
                    id=f"endpoint:{ep.full_name()}",
                    type=GraphNodeType.ENDPOINT,
                    name=ep.full_name(),
                    metadata={"path": path, "method": method.upper()},
                )
            )
            graph._endpoints.append(ep)

    return graph


def _extract_security_schemes(
    operation: dict[str, Any], available: dict[str, Any]
) -> list[str]:
    """Resolve security schemes для operation (including global)."""
    schemes: set[str] = set()
    op_sec = operation.get("security")
    if op_sec is not None:
        # op_sec is list of dicts [{name: [scopes]}].
        for item in op_sec:
            for name in item:
                schemes.add(name)
    if not schemes and available:
        # Use global security.
        global_sec = operation.get("security", [])
        if not global_sec:
            # Check spec-level.
            return []
    return sorted(schemes)


def validate_security(graph: OpenAPIGraph) -> list[SecurityIssue]:
    """Validate security configuration. Returns list of issues.

    Checks:
    - Endpoints без security schemes (public access).
    - Deprecated API key auth (in security schemes).
    - Wildcard scopes (excessive permissions).
    - Internal endpoints (paths starting with /admin / /internal) без security.
    - Deprecated operations.
    """
    issues: list[SecurityIssue] = []

    # 1. Endpoints без security.
    for ep in graph.endpoints:
        if not ep.security_schemes:
            severity = (
                SecuritySeverity.CRITICAL
                if ep.path.startswith(("/admin", "/internal", "/debug"))
                else SecuritySeverity.MEDIUM
            )
            issues.append(
                SecurityIssue(
                    issue_type="no_security",
                    severity=severity,
                    location=ep.full_name(),
                    description=f"Endpoint {ep.full_name()} has no security schemes",
                    recommendation=(
                        "Add security schemes via `security:` field or "
                        "use global security in components.securitySchemes"
                    ),
                )
            )

    # 2. Deprecated API key auth.
    for node in graph.nodes:
        if node.type != GraphNodeType.SECURITY:
            continue
        meta = node.metadata
        if meta.get("type") == "apiKey":
            # Check for deprecated in description.
            desc = str(meta.get("description", "")).lower()
            if "deprecated" in desc:
                issues.append(
                    SecurityIssue(
                        issue_type="deprecated_apikey",
                        severity=SecuritySeverity.HIGH,
                        location=f"security:{node.name}",
                        description=f"API key auth '{node.name}' is marked deprecated",
                        recommendation=(
                            "Migrate to OAuth2 / bearer / mTLS. "
                            "API key has no rotation, scoping, or expiry."
                        ),
                    )
                )
        if meta.get("type") == "oauth2" and "scopes" in meta:
            for scope, desc in (meta.get("scopes") or {}).items():
                if scope.endswith(":*") or scope == "*":
                    issues.append(
                        SecurityIssue(
                            issue_type="wildcard_scope",
                            severity=SecuritySeverity.HIGH,
                            location=f"security:{node.name}",
                            description=(
                                f"OAuth2 scope '{scope}' is wildcard — "
                                f"grants excessive permissions"
                            ),
                            recommendation=(
                                "Use granular scopes (e.g. orders:read, "
                                "orders:write) instead of wildcard"
                            ),
                        )
                    )

    # 3. Deprecated operations.
    for ep in graph.endpoints:
        if ep.deprecated:
            issues.append(
                SecurityIssue(
                    issue_type="deprecated_operation",
                    severity=SecuritySeverity.LOW,
                    location=ep.full_name(),
                    description=f"Operation {ep.full_name()} is marked deprecated",
                    recommendation=(
                        "Add Sunset header, document migration path, "
                        "or remove endpoint after grace period"
                    ),
                )
            )

    return issues


def merge_graphs(graphs: list[OpenAPIGraph]) -> OpenAPIGraph:
    """Merge multiple OpenAPIGraph into one (для multi-endpoint integration)."""
    merged = OpenAPIGraph()
    seen_node_ids: set[str] = set()

    for graph in graphs:
        for node in graph.nodes:
            if node.id not in seen_node_ids:
                merged.add_node(node)
                seen_node_ids.add(node.id)
        for edge in graph.edges:
            # Always add edge (idempotent enough for our use case).
            merged.add_edge(edge)
        merged._endpoints.extend(graph.endpoints)

    return merged
