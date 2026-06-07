"""Unit tests for Mobile BFF (S50 W3, v21 §7.2)."""

# ruff: noqa: S101

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.mobile.router import (
    add_test_notification,
    mobile_router,
    reset_mobile_state,
)
from src.backend.entrypoints.api.mobile.schemas import (
    CompressedResponse,
    CursorPage,
    MobileNotification,
    MobileProfile,
    PayloadOptimizer,
    PushTokenRequest,
)


@pytest.fixture
def client() -> TestClient:
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(mobile_router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def reset() -> None:
    reset_mobile_state()


def _auth(user_id: str = "user_test") -> dict[str, str]:
    return {"Authorization": f"Bearer mobile:{user_id}:abc123"}


# ── Auth ─────────────────────────────────────────────────────────────


def test_login_returns_tokens(client: TestClient) -> None:
    resp = client.post("/mobile/v1/auth/login?device_id=abc12345&tenant_id=acme")
    assert resp.status_code == 200
    data = resp.json()
    # device_id[:8] = "abc12345" → user_id = "user_abc12345"
    # Token format: mobile:<user_id>:<hex>
    assert data["access_token"].startswith("mobile:user_abc12345:")
    assert data["refresh_token"].startswith("mobile-refresh:user_abc12345:")
    assert data["expires_in"] == 900
    assert data["token_type"] == "Bearer"


def test_profile_requires_auth(client: TestClient) -> None:
    resp = client.get("/mobile/v1/profile")
    assert resp.status_code == 401


def test_profile_invalid_token(client: TestClient) -> None:
    resp = client.get(
        "/mobile/v1/profile", headers={"Authorization": "Bearer invalid_token"}
    )
    assert resp.status_code == 401


def test_profile_default_user(client: TestClient) -> None:
    resp = client.get("/mobile/v1/profile", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["user_id"] == "user_test"
    assert body["data"]["display_name"].startswith("User ")
    assert body["compressed"] is True
    assert "request_id" in body
    assert "timestamp" in body


# ── Notifications ────────────────────────────────────────────────────


def test_notifications_empty(client: TestClient) -> None:
    resp = client.get("/mobile/v1/notifications", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["items"] == []
    # has_more is False → next_cursor omitted by optimizer (None dropped)
    assert body["data"]["has_more"] is False
    # next_cursor may be absent (None dropped by optimizer) or present
    assert body["data"].get("next_cursor") is None


def test_notifications_paginated(client: TestClient) -> None:
    user_id = "user_test"
    for i in range(5):
        add_test_notification(
            user_id,
            MobileNotification(
                id=f"n-{i}",
                title=f"Title {i}",
                body="body",
                created_at=datetime.now(tz=timezone.utc),
            ),
        )
    # First page
    resp = client.get("/mobile/v1/notifications?limit=2", headers=_auth(user_id))
    body = resp.json()
    assert len(body["data"]["items"]) == 2
    # next_cursor IS present (non-None) when has_more
    assert body["data"]["next_cursor"] == "2"
    assert body["data"]["has_more"] is True
    assert body["data"]["total_estimated"] == 5
    # Second page
    resp = client.get(
        "/mobile/v1/notifications?limit=2&cursor=2", headers=_auth(user_id)
    )
    body = resp.json()
    assert len(body["data"]["items"]) == 2
    assert body["data"]["next_cursor"] == "4"
    # Last page
    resp = client.get(
        "/mobile/v1/notifications?limit=2&cursor=4", headers=_auth(user_id)
    )
    body = resp.json()
    assert len(body["data"]["items"]) == 1
    # next_cursor dropped (None)
    assert body["data"].get("next_cursor") is None
    assert body["data"]["has_more"] is False


def test_notifications_limit_bounds(client: TestClient) -> None:
    # limit > 100 → 422
    resp = client.get("/mobile/v1/notifications?limit=200", headers=_auth())
    assert resp.status_code == 422


# ── Push tokens ─────────────────────────────────────────────────────


def test_register_push_token(client: TestClient) -> None:
    resp = client.post(
        "/mobile/v1/push-token",
        headers=_auth(),
        json={"token": "fcm_token_abc", "platform": "android", "device_id": "device-1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["registered"] is True
    assert resp.json()["data"]["platform"] == "android"


def test_register_push_token_requires_auth(client: TestClient) -> None:
    resp = client.post(
        "/mobile/v1/push-token",
        json={"token": "x", "platform": "ios", "device_id": "d"},
    )
    assert resp.status_code == 401


def test_register_push_token_validation(client: TestClient) -> None:
    resp = client.post(
        "/mobile/v1/push-token",
        headers=_auth(),
        json={"token": "x"},  # missing platform, device_id
    )
    assert resp.status_code == 422


# ── Sync ─────────────────────────────────────────────────────────────


def test_sync_state(client: TestClient) -> None:
    resp = client.get("/mobile/v1/sync", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert "last_sync_at" in body["data"]
    assert body["data"]["server_version"] == 1
    assert body["data"]["changes"] == []


# ── Health ───────────────────────────────────────────────────────────


def test_health_no_auth(client: TestClient) -> None:
    """Health endpoint doesn't require auth (liveness)."""
    resp = client.get("/mobile/v1/health")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "ok"


# ── Payload optimizer ───────────────────────────────────────────────


def test_payload_optimizer_drops_nulls() -> None:
    data = {"a": 1, "b": None, "c": "x"}
    result = PayloadOptimizer.compact(data)
    assert result == {"a": 1, "c": "x"}
    assert "b" not in result


def test_payload_optimizer_truncates_long_strings() -> None:
    long_str = "x" * 500
    data = {"text": long_str}
    result = PayloadOptimizer.compact(data)
    assert len(result["text"]) == PayloadOptimizer.MAX_STRING_LENGTH


def test_payload_optimizer_converts_datetime_to_timestamp() -> None:
    dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    data = {"created": dt}
    result = PayloadOptimizer.compact(data)
    assert isinstance(result["created"], int)
    assert result["created"] == int(dt.timestamp())


def test_payload_optimizer_nested() -> None:
    data = {
        "items": [
            {"id": 1, "name": "a", "extra": None},
            {"id": 2, "name": "b", "extra": None},
        ],
        "total": 2,
    }
    result = PayloadOptimizer.compact(data)
    assert len(result["items"]) == 2
    assert "extra" not in result["items"][0]


def test_payload_optimizer_reduction_pct() -> None:
    data = {"a": 1, "b": None, "c": None, "d": 4}
    optimized = PayloadOptimizer.compact(data)
    reduction = PayloadOptimizer.reduction_pct(data, optimized)
    assert reduction > 0  # Should be > 0% since we dropped nulls


# ── Schemas ──────────────────────────────────────────────────────────


def test_mobile_profile_required_fields() -> None:
    p = MobileProfile(user_id="u-1", display_name="John", tenant_id="acme")
    assert p.user_id == "u-1"
    assert p.role == "user"  # default
    assert p.unread_count == 0  # default


def test_cursor_page_defaults() -> None:
    page = CursorPage(items=[1, 2, 3])
    assert page.next_cursor is None
    assert page.has_more is False
    assert page.total_estimated is None


def test_compressed_response_metadata() -> None:
    cr = CompressedResponse(
        data={"x": 1}, timestamp=datetime.now(tz=timezone.utc), request_id="abc"
    )
    assert cr.compressed is False  # default — router sets True explicitly
    assert cr.schema_version == 1  # default


def test_push_token_request_required() -> None:
    req = PushTokenRequest(token="x", platform="ios", device_id="d-1")
    assert req.platform == "ios"
