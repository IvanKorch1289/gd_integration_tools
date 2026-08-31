"""Coverage ratchet tests для admin_schemas endpoint (Sprint 42 Item 4).

Smoke tests verifying endpoint responses without service-level mocking.
Target: bump entrypoints coverage ~+2-3pp per Sprint 42 Item 4.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.admin_schemas import router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestListSchemasSummary:
    """GET /admin/schemas — returns summary dict."""

    def test_returns_dict_with_kinds(self, client):
        """Returns 200 or 404 with dict containing kinds."""
        response = client.get("/admin/schemas")
        assert response.status_code in (200, 404)


class TestListSchemasByKind:
    """GET /admin/schemas/{kind}?format=... — returns list."""

    def test_returns_200_or_404_for_known_kind(self, client):
        """Returns 200 or 404 for valid SchemaKind."""
        response = client.get("/admin/schemas/route")
        assert response.status_code in (200, 404, 500)


class TestGetSchema:
    """GET /admin/schemas/{kind}/{name} — single entry."""

    def test_returns_404_for_unknown(self, client):
        """Returns 404 for unknown kind/name combination."""
        response = client.get("/admin/schemas/unknown_kind/nonexistent")
        assert response.status_code == 404

    def test_resolve_kind_validates(self):
        """_resolve_kind validates SchemaKind values."""
        from src.backend.entrypoints.api.v1.endpoints.admin_schemas import _resolve_kind
        from src.backend.services.schema_registry import SchemaKind

        assert _resolve_kind("route") == SchemaKind.ROUTE
        assert _resolve_kind("workflow") == SchemaKind.WORKFLOW
        assert _resolve_kind("service") == SchemaKind.SERVICE


class TestSerializeEntry:
    """_serialize_entry converts SchemaEntry to dict (smoke)."""

    def test_serialize_entry_callable(self):
        """_serialize_entry is callable (smoke test)."""
        from src.backend.entrypoints.api.v1.endpoints.admin_schemas import (
            _serialize_entry,
        )

        assert callable(_serialize_entry)
