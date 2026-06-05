# ruff: noqa: S101
"""Smoke tests for CDC client (infrastructure/clients/external/cdc.py)."""

from __future__ import annotations

from src.backend.infrastructure.clients.external.cdc import CDCEvent, CDCSubscription

# ── CDCEvent dataclass ──────────────────────────────────────────────


def test_cdc_event_minimal() -> None:
    event = CDCEvent(
        table="users",
        operation="INSERT",
        timestamp="2026-06-05T00:00:00Z",
        profile="default",
        new={"id": 1, "name": "alice"},
    )
    assert event.table == "users"
    assert event.operation == "INSERT"
    assert event.new == {"id": 1, "name": "alice"}


def test_cdc_event_with_old() -> None:
    event = CDCEvent(
        table="users",
        operation="UPDATE",
        timestamp="2026-06-05T00:00:00Z",
        profile="default",
        new={"id": 1, "name": "alice2"},
        old={"id": 1, "name": "alice"},
    )
    assert event.operation == "UPDATE"
    assert event.old is not None
    assert event.old["name"] == "alice"


def test_cdc_event_to_dict() -> None:
    event = CDCEvent(
        table="orders",
        operation="DELETE",
        timestamp="2026-06-05T00:00:00Z",
        profile="default",
        old={"id": 99},
    )
    d = event.to_dict()
    assert isinstance(d, dict)
    assert d["table"] == "orders"
    assert d["operation"] == "DELETE"
    assert "old" in d
    assert "new" in d


# ── CDCSubscription dataclass ──────────────────────────────────────


def test_cdc_subscription_defaults() -> None:
    sub = CDCSubscription()
    assert sub.id != ""  # uuid generated
    assert sub.profile == ""
    assert sub.tables == []
    assert sub.strategy == "polling"
    assert sub.interval == 5.0
    assert sub.batch_size == 100
    assert sub.timestamp_column == "updated_at"
    assert sub.channel is None
    assert sub.callback is None
    assert sub.target_action is None
    assert sub.active is True


def test_cdc_subscription_custom() -> None:
    sub = CDCSubscription(
        profile="prod",
        tables=["users", "orders"],
        strategy="logminer",
        interval=10.0,
        active=False,
    )
    assert sub.profile == "prod"
    assert sub.tables == ["users", "orders"]
    assert sub.strategy == "logminer"
    assert sub.interval == 10.0
    assert sub.active is False


# ── Module exports ─────────────────────────────────────────────────


def test_module_imports() -> None:
    from src.backend.infrastructure.clients.external import cdc

    assert hasattr(cdc, "CDCEvent")
    assert hasattr(cdc, "CDCSubscription")
    assert hasattr(cdc, "CDCClient")
    assert hasattr(cdc, "get_cdc_client")


# ── get_cdc_client: at least importable ─────────────────────────────


def test_get_cdc_client_callable() -> None:
    from src.backend.infrastructure.clients.external.cdc import get_cdc_client

    assert callable(get_cdc_client)
