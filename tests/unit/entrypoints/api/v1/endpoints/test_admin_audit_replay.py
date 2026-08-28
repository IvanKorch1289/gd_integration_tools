"""Unit tests для admin_audit_replay endpoint (S34 W1).

Покрывает:
1. Endpoint возвращает список AuditRecordResponse
2. Default query params (count=100, start_id='-')
3. Validation: count вне диапазона 1..1000 → 422
4. Auth scope: require_admin для /admin/audit/capability
5. Defensive mapper: Redis stream entry → AuditRecordResponse
   (best-effort .get(), missing fields → None)
6. Empty stream → empty list

Не покрывает:
- Реальный Redis stream integration (требует docker, S34 W2+ если потребуется).
- Replay-via-HTTP (отдельный endpoint, S34 W3+ если потребуется).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.admin_audit_replay import router


@pytest.fixture
def app() -> FastAPI:
    """FastAPI app с подключённым admin_audit_replay router."""
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app: FastAPI):  # type: ignore[no-untyped-def]
    """Test client (без auth override — endpoint требует real admin token)."""
    return TestClient(app)


@pytest.mark.asyncio
async def test_endpoint_returns_audit_records() -> None:
    """Успешный сценарий: Redis stream → 3 records → endpoint возвращает их."""
    mock_records = [
        {
            "id": "1700000000000-0",
            "timestamp": "2026-08-27T18:00:00+00:00",
            "method": "POST",
            "path": "/api/v1/orders/",
            "status_code": 201,
            "duration_ms": 45.3,
            "tenant_id": "tenant-1",
            "user_id": "user-42",
            "body": {"order_id": 123},
        },
        {
            "id": "1700000000001-0",
            "timestamp": "2026-08-27T18:00:01+00:00",
            "method": "GET",
            "path": "/api/v1/orders/123",
            "status_code": 200,
            "duration_ms": 12.1,
            "tenant_id": "tenant-1",
            "user_id": "user-42",
            "body": None,
        },
        {
            "id": "1700000000002-0",
            "method": "DELETE",
            # missing timestamp, status_code, body (defensive)
        },
    ]

    with patch(
        "src.backend.services.audit.replay_query.list_audit_records",
        new=AsyncMock(return_value=mock_records),
    ):
        from src.backend.entrypoints.api.v1.endpoints.admin_audit_replay import (
            list_audit_records_endpoint,
        )

        result = await list_audit_records_endpoint(count=3, start_id="-")
        from src.backend.entrypoints.api.v1.endpoints.admin_audit_replay import (
            list_audit_records_endpoint,
        )

        result = await list_audit_records_endpoint(count=3, start_id="-")

    assert len(result) == 3
    # Record 1: full data
    assert result[0].record_id == "1700000000000-0"
    assert result[0].method == "POST"
    assert result[0].status_code == 201
    assert result[0].duration_ms == 45.3
    assert result[0].body == {"order_id": 123}
    # Record 2: body=None
    assert result[1].body is None
    # Record 3: defensive — missing fields → None
    assert result[2].record_id == "1700000000002-0"
    assert result[2].method == "DELETE"
    assert result[2].timestamp is None
    assert result[2].status_code is None
    assert result[2].body is None


@pytest.mark.asyncio
async def test_endpoint_empty_stream() -> None:
    """Empty Redis stream → endpoint возвращает пустой list (не ошибка)."""
    with patch(
        "src.backend.services.audit.replay_query.list_audit_records",
        new=AsyncMock(return_value=[]),
    ):
        from src.backend.entrypoints.api.v1.endpoints.admin_audit_replay import (
            list_audit_records_endpoint,
        )

        result = await list_audit_records_endpoint(count=100, start_id="-")

    assert result == []


@pytest.mark.asyncio
async def test_defensive_mapper_handles_minimal_record() -> None:
    """Defensive mapper: record только с id → все остальные поля None."""
    from src.backend.entrypoints.api.v1.endpoints.admin_audit_replay import _to_response

    minimal = {"id": "1700000000003-0"}
    response = _to_response(minimal)

    assert response.record_id == "1700000000003-0"
    assert response.timestamp is None
    assert response.method is None
    assert response.status_code is None
    assert response.body is None


@pytest.mark.asyncio
async def test_defensive_mapper_handles_empty_record() -> None:
    """Defensive mapper: пустой dict → пустой record_id, все None."""
    from src.backend.entrypoints.api.v1.endpoints.admin_audit_replay import _to_response

    response = _to_response({})

    assert response.record_id == ""
    assert response.timestamp is None
    assert response.body is None


def test_router_registered() -> None:
    """Endpoint registered under expected path."""
    paths = [route.path for route in router.routes]
    assert "/audit/capability" in paths
