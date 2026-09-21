"""Focused tests for ``core.api_graph`` (Wave 2 DX #56 — security + graph).

Проверяем:
- ``import_openapi_graph`` парсит spec в graph.
- Schema nodes + ref edges строятся корректно.
- Endpoint nodes + consumes/produces edges.
- Security scheme nodes + secured_by edges.
- ``schema_references`` / ``endpoints_using_schema`` queries.
- ``find_cycles`` / ``find_orphans`` детекция.
- ``validate_security`` ловит issues: no security, deprecated apikey,
  wildcard scope, deprecated ops.
- ``merge_graphs`` для multi-endpoint integration.
"""

from __future__ import annotations

from src.backend.core.api_graph import (
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

SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Orders API", "version": "1.0.0"},
    "paths": {
        "/orders": {
            "get": {
                "operationId": "listOrders",
                "summary": "List orders",
                "tags": ["orders"],
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/OrderList"}
                            }
                        }
                    }
                },
            },
            "post": {
                "operationId": "createOrder",
                "summary": "Create order",
                "tags": ["orders"],
                "security": [{"bearerAuth": []}],
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/Order"}
                        }
                    }
                },
                "responses": {
                    "201": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Order"}
                            }
                        }
                    }
                },
            },
        },
        "/admin/orders": {
            "get": {
                "operationId": "listAllOrders",
                "summary": "List all orders (admin)",
                "deprecated": True,
                "responses": {"200": {"description": "OK"}},
            }
        },
    },
    "components": {
        "schemas": {
            "Order": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "customer": {"$ref": "#/components/schemas/Customer"},
                },
            },
            "Customer": {"type": "object", "properties": {"name": {"type": "string"}}},
            "OrderList": {
                "type": "array",
                "items": {"$ref": "#/components/schemas/Order"},
            },
        },
        "securitySchemes": {
            "bearerAuth": {"type": "http", "scheme": "bearer"},
            "apiKeyAuth": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "DEPRECATED — use OAuth2",
            },
            "oauth2": {
                "type": "oauth2",
                "scopes": {
                    "orders:read": "Read orders",
                    "orders:*": "Full orders access",
                },
            },
        },
    },
}


class TestImportOpenAPIGraph:
    def test_imports_schema_nodes(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        schema_ids = [n.id for n in g.nodes if n.type == GraphNodeType.SCHEMA]
        assert "schema:Order" in schema_ids
        assert "schema:Customer" in schema_ids
        assert "schema:OrderList" in schema_ids

    def test_imports_endpoint_nodes(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        ep_ids = [n.id for n in g.nodes if n.type == GraphNodeType.ENDPOINT]
        assert "endpoint:GET /orders" in ep_ids
        assert "endpoint:POST /orders" in ep_ids

    def test_imports_security_nodes(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        sec_ids = [n.id for n in g.nodes if n.type == GraphNodeType.SECURITY]
        assert "security:bearerAuth" in sec_ids
        assert "security:apiKeyAuth" in sec_ids
        assert "security:oauth2" in sec_ids

    def test_schema_ref_edges(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        # Order → Customer.
        refs = g.schema_references("Order")
        assert "schema:Customer" in refs
        # OrderList → Order.
        refs2 = g.schema_references("OrderList")
        assert "schema:Order" in refs2

    def test_endpoint_consumes_produces_edges(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        # POST /orders consumes Order.
        producing = [
            edge
            for edge in g.edges
            if edge.source == "endpoint:POST /orders" and edge.kind == "consumes"
        ]
        assert any(edge.target == "schema:Order" for edge in producing)

    def test_endpoint_security_edges(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        # POST /orders secured by bearerAuth.
        sec_edges = [
            edge
            for edge in g.edges
            if edge.source == "endpoint:POST /orders" and edge.kind == "secured_by"
        ]
        assert any(edge.target == "security:bearerAuth" for edge in sec_edges)

    def test_endpoint_count(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        assert len(g.endpoints) == 3  # GET /orders, POST /orders, GET /admin/orders.

    def test_deprecated_flag(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        admin_ep = next(ep for ep in g.endpoints if ep.path == "/admin/orders")
        assert admin_ep.deprecated is True


class TestGraphQueries:
    def test_schema_references_chain(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        # OrderList → Order → Customer.
        assert "schema:Order" in g.schema_references("OrderList")
        assert "schema:Customer" in g.schema_references("Order")

    def test_endpoints_using_schema(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        # Order used by POST /orders (consumes + produces).
        eps = g.endpoints_using_schema("Order")
        names = [ep.full_name() for ep in eps]
        assert "POST /orders" in names
        # GET /orders produces OrderList (not Order).
        eps_list = g.endpoints_using_schema("OrderList")
        list_names = [ep.full_name() for ep in eps_list]
        assert "GET /orders" in list_names

    def test_endpoints_using_customer(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        # Customer is referenced only by Order, not directly by any endpoint.
        # endpoints_using_schema returns direct endpoints only (not transitive).
        eps = g.endpoints_using_schema("Customer")
        assert eps == []  # No direct endpoint → Customer.
        # Order is referenced by POST /orders (consumes + produces).
        eps_order = g.endpoints_using_schema("Order")
        names = [ep.full_name() for ep in eps_order]
        assert "POST /orders" in names

    def test_find_orphans(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        orphans = g.find_orphans()
        # Customer has only Order referencing it → not orphan.
        # No schemas without incoming edges in this spec.
        assert "schema:Customer" not in orphans


class TestCycleDetection:
    def test_no_cycles(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        assert g.find_cycles() == []

    def test_cycle_detected(self) -> None:
        spec = {
            "openapi": "3.0.0",
            "info": {"title": "T", "version": "1.0"},
            "paths": {},
            "components": {
                "schemas": {
                    "A": {"$ref": "#/components/schemas/B"},
                    "B": {"$ref": "#/components/schemas/A"},
                }
            },
        }
        g = import_openapi_graph(spec)
        cycles = g.find_cycles()
        assert len(cycles) >= 1


class TestValidateSecurity:
    def test_no_security_endpoint(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        issues = validate_security(g)
        # GET /orders и GET /admin/orders не имеют security.
        no_sec = [i for i in issues if i.issue_type == "no_security"]
        assert len(no_sec) >= 2

    def test_admin_endpoint_critical(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        issues = validate_security(g)
        admin = next(
            i
            for i in issues
            if i.location == "GET /admin/orders" and i.issue_type == "no_security"
        )
        assert admin.severity == SecuritySeverity.CRITICAL

    def test_deprecated_apikey_detected(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        issues = validate_security(g)
        apikey = [i for i in issues if i.issue_type == "deprecated_apikey"]
        assert len(apikey) == 1
        assert apikey[0].location == "security:apiKeyAuth"

    def test_wildcard_scope_detected(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        issues = validate_security(g)
        wild = [i for i in issues if i.issue_type == "wildcard_scope"]
        assert len(wild) == 1
        assert "orders:*" in wild[0].location or "orders:*" in wild[0].description

    def test_deprecated_operation_detected(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        issues = validate_security(g)
        deprecated = [i for i in issues if i.issue_type == "deprecated_operation"]
        assert len(deprecated) == 1
        assert deprecated[0].location == "GET /admin/orders"

    def test_no_issues_for_clean_spec(self) -> None:
        clean_spec = {
            "openapi": "3.0.0",
            "info": {"title": "Clean", "version": "1.0"},
            "paths": {
                "/x": {
                    "get": {
                        "summary": "X",
                        "security": [{"bearerAuth": []}],
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {
                "securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}
            },
        }
        g = import_openapi_graph(clean_spec)
        issues = validate_security(g)
        # Only no_security or deprecated issues should appear (none in this case).
        assert issues == []


class TestMergeGraphs:
    def test_merge_two_graphs(self) -> None:
        spec1 = SAMPLE_SPEC
        spec2 = {
            "openapi": "3.0.0",
            "info": {"title": "B", "version": "1.0"},
            "paths": {
                "/users": {
                    "get": {
                        "summary": "List users",
                        "responses": {"200": {"description": "OK"}},
                    }
                }
            },
            "components": {"schemas": {"User": {"type": "object"}}},
        }
        g1 = import_openapi_graph(spec1)
        g2 = import_openapi_graph(spec2)
        merged = merge_graphs([g1, g2])

        # Both schemas present.
        assert merged.get_node("schema:Order") is not None
        assert merged.get_node("schema:User") is not None
        # Both endpoints.
        ep_ids = [n.id for n in merged.nodes if n.type == GraphNodeType.ENDPOINT]
        assert "endpoint:GET /orders" in ep_ids
        assert "endpoint:GET /users" in ep_ids


class TestGraphNode:
    def test_defaults(self) -> None:
        n = GraphNode(id="schema:X", type=GraphNodeType.SCHEMA, name="X")
        assert n.metadata == {}


class TestGraphEdge:
    def test_defaults(self) -> None:
        e = GraphEdge(source="A", target="B", kind="ref")
        assert e.metadata == {}


class TestEndpointNode:
    def test_defaults(self) -> None:
        e = EndpointNode(path="/x", method="GET")
        assert e.tags == []
        assert e.deprecated is False


class TestSecurityIssue:
    def test_defaults(self) -> None:
        i = SecurityIssue(issue_type="x", severity=SecuritySeverity.LOW, location="y")
        assert i.recommendation == ""


class TestOpenAPIGraph:
    def test_init(self) -> None:
        g = OpenAPIGraph()
        assert g.nodes == []
        assert g.edges == []
        assert g.endpoints == []

    def test_add_node(self) -> None:
        g = OpenAPIGraph()
        n = GraphNode(id="schema:X", type=GraphNodeType.SCHEMA, name="X")
        g.add_node(n)
        assert g.get_node("schema:X") is n

    def test_add_edge(self) -> None:
        g = OpenAPIGraph()
        g.add_node(GraphNode(id="A", type=GraphNodeType.SCHEMA, name="A"))
        g.add_node(GraphNode(id="B", type=GraphNodeType.SCHEMA, name="B"))
        g.add_edge(GraphEdge(source="A", target="B", kind="ref"))
        assert len(g.edges) == 1

    def test_to_dict(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        d = g.to_dict()
        assert "node_count" in d
        assert "edge_count" in d
        assert "endpoint_count" in d
        assert d["endpoint_count"] == 3

    def test_clear(self) -> None:
        g = import_openapi_graph(SAMPLE_SPEC)
        g.clear()
        assert g.nodes == []
        assert g.edges == []
        assert g.endpoints == []


class TestSingleton:
    def test_import_function_isolated(self) -> None:
        """import_openapi_graph каждый раз возвращает fresh graph."""
        g1 = import_openapi_graph(SAMPLE_SPEC)
        g2 = import_openapi_graph(SAMPLE_SPEC)
        assert g1 is not g2
        # Same content though.
        assert len(g1.nodes) == len(g2.nodes)


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import api_graph

        assert len(api_graph.__all__) == 10


class TestRealisticExample:
    """Realistic: import Petstore + run security validation."""

    def test_petstore_security_check(self) -> None:
        petstore = {
            "openapi": "3.0.0",
            "info": {"title": "Petstore", "version": "1.0.0"},
            "paths": {
                "/pets": {
                    "get": {
                        "summary": "List pets",
                        "security": [{"api_key": []}],
                        "responses": {"200": {"description": "OK"}},
                    },
                    "post": {
                        "summary": "Create pet",
                        "security": [{"api_key": []}],
                        "responses": {"201": {"description": "Created"}},
                    },
                },
                "/admin/dump": {
                    "get": {
                        "summary": "Admin dump",
                        "responses": {"200": {"description": "OK"}},
                    }
                },
            },
            "components": {
                "securitySchemes": {
                    "api_key": {
                        "type": "apiKey",
                        "in": "header",
                        "name": "X-API-Key",
                        "description": "DEPRECATED — please use OAuth2 in production",
                    }
                }
            },
        }
        g = import_openapi_graph(petstore)
        issues = validate_security(g)

        # Admin endpoint без security → CRITICAL.
        admin = [
            i
            for i in issues
            if i.issue_type == "no_security" and i.location == "GET /admin/dump"
        ]
        assert len(admin) == 1
        assert admin[0].severity == SecuritySeverity.CRITICAL

        # Deprecated API key → HIGH.
        apikey = [i for i in issues if i.issue_type == "deprecated_apikey"]
        assert len(apikey) == 1
        assert apikey[0].severity == SecuritySeverity.HIGH
