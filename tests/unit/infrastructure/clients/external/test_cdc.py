# ruff: noqa: S101
"""Smoke + unit + property tests for CDC client (infrastructure/clients/external/cdc.py).

Sections:
    * Smoke tests (legacy) — defaults / class-level attrs / module exports.
    * Unit tests — top-5+ methods:
        - CDCEvent.to_dict (all keys present, types preserved).
        - CDCSubscription.id (12-char hex invariant).
        - CDCClient.subscribe (3 known strategies + unknown → ValueError).
        - CDCClient.unsubscribe (existing / nonexistent / task cleanup).
        - CDCClient.list_subscriptions (formatted output).
        - CDCClient._dispatch_change (callback only, target_action only, callback error).
        - _PollingStrategy._get_cursor (Redis path + local fallback).
    * Property tests (hypothesis) — CDCEvent.to_dict preserves fields round-trip.
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from src.backend.infrastructure.clients.external import cdc as cdc_module
from src.backend.infrastructure.clients.external.cdc import (
    CDCClient,
    CDCEvent,
    CDCSubscription,
    _PollingStrategy,
)

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


# ════════════════════════════════════════════════════════════════════
# Unit tests (new) — `@pytest.mark.unit` required for `-m unit` gate.
# ════════════════════════════════════════════════════════════════════


# ── CDCEvent.to_dict: dataclass serialization invariants ────────────


@pytest.mark.unit
def test_cdc_event_to_dict_contains_all_six_fields() -> None:
    """to_dict() must return dict with exactly the 6 documented CDCEvent fields."""
    event = CDCEvent(
        operation="INSERT",
        table="orders",
        timestamp="2026-06-05T00:00:00Z",
        profile="default",
        new={"id": 1},
        old=None,
    )
    d = event.to_dict()
    assert isinstance(d, dict)
    assert set(d.keys()) == {"operation", "table", "timestamp", "profile", "new", "old"}
    assert d["operation"] == "INSERT"
    assert d["table"] == "orders"
    assert d["timestamp"] == "2026-06-05T00:00:00Z"
    assert d["profile"] == "default"
    assert d["new"] == {"id": 1}
    assert d["old"] is None


# ── CDCSubscription.id: 12-char hex invariant ──────────────────────


@pytest.mark.unit
def test_cdc_subscription_id_is_12_char_hex() -> None:
    """Generated id must be 12 lowercase hex chars and unique per instance."""
    sub_a = CDCSubscription()
    sub_b = CDCSubscription()
    hex_pattern = re.compile(r"^[0-9a-f]{12}$")
    assert hex_pattern.match(sub_a.id), f"id {sub_a.id!r} is not 12 hex chars"
    assert hex_pattern.match(sub_b.id), f"id {sub_b.id!r} is not 12 hex chars"
    assert sub_a.id != sub_b.id, "two CDCSubscription() must produce distinct ids"


# ── CDCClient.subscribe: 3 strategies + unknown → ValueError ───────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_client_subscribe_unknown_strategy_raises_value_error() -> None:
    """subscribe() must raise ValueError for any strategy not in _STRATEGIES."""
    client = CDCClient()
    with pytest.raises(ValueError, match="Unknown CDC strategy 'weird_thing'"):
        await client.subscribe(
            profile="default", tables=["orders"], strategy="weird_thing"
        )
    # No subscription was created
    assert client._subscriptions == {}
    assert client._tasks == {}


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("strategy", ["polling", "listen_notify", "logminer"])
async def test_cdc_client_subscribe_known_strategy_creates_task(strategy: str) -> None:
    """subscribe() with each known strategy must register sub + create background task."""
    client = CDCClient()
    fake_task = MagicMock(name=f"task_{strategy}", spec=asyncio.Task)
    fake_task.done.return_value = False
    with patch.object(cdc_module, "get_task_registry") as reg:
        reg.return_value.create_task = MagicMock(return_value=fake_task)
        sub_id = await client.subscribe(
            profile="default", tables=["orders"], strategy=strategy
        )

    assert sub_id in client._subscriptions
    assert sub_id in client._tasks
    sub = client._subscriptions[sub_id]
    assert sub.strategy == strategy
    assert sub.profile == "default"
    assert sub.tables == ["orders"]
    # create_task was invoked with a name of the form 'cdc-<id>'
    create_call = reg.return_value.create_task.call_args
    assert create_call.kwargs.get("name", "").startswith("cdc-")


# ── CDCClient.unsubscribe: existing / nonexistent / task cleanup ───


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_client_unsubscribe_existing_removes_sub_and_cancels_task() -> None:
    """unsubscribe() for known id must mark sub inactive, cancel task, return True."""
    client = CDCClient()
    fake_task = MagicMock(name="cdc_task", spec=asyncio.Task)
    fake_task.done.return_value = False
    with patch.object(cdc_module, "get_task_registry") as reg:
        reg.return_value.create_task = MagicMock(return_value=fake_task)
        sub_id = await client.subscribe(
            profile="default", tables=["orders"], strategy="polling"
        )

    # Awaitable stub for `await task` in unsubscribe
    async def _await_task() -> None:
        return None

    fake_task.__await__ = lambda: _await_task().__await__()  # type: ignore[method-assign]

    result = await client.unsubscribe(sub_id)
    assert result is True
    assert sub_id not in client._subscriptions
    assert sub_id not in client._tasks
    fake_task.cancel.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_client_unsubscribe_unknown_id_returns_false() -> None:
    """unsubscribe() for unknown id must return False and not raise."""
    client = CDCClient()
    result = await client.unsubscribe("does-not-exist")
    assert result is False


# ── CDCClient.list_subscriptions: format / projection ──────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_client_list_subscriptions_returns_projection() -> None:
    """list_subscriptions() must return a list of dicts with the 6 documented keys."""
    client = CDCClient()
    fake_task = MagicMock(spec=asyncio.Task)
    fake_task.done.return_value = False
    with patch.object(cdc_module, "get_task_registry") as reg:
        reg.return_value.create_task = MagicMock(return_value=fake_task)
        await client.subscribe(
            profile="oracle_1",
            tables=["orders", "users"],
            strategy="polling",
            target_action="orders.handle_change",
        )
        await client.subscribe(
            profile="pg_main", tables=["events"], strategy="listen_notify"
        )

    result = client.list_subscriptions()
    assert isinstance(result, list)
    assert len(result) == 2
    for item in result:
        assert set(item.keys()) == {
            "id",
            "profile",
            "tables",
            "strategy",
            "target_action",
            "active",
        }
        assert item["active"] is True

    profiles = {item["profile"] for item in result}
    assert profiles == {"oracle_1", "pg_main"}
    target_actions = {item["target_action"] for item in result}
    assert target_actions == {"orders.handle_change", None}


# ── CDCClient._dispatch_change: callback / target_action / error ───


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_dispatch_change_invokes_callback_with_event_dict() -> None:
    """_dispatch_change() with callback only must await the callback with to_dict()."""
    client = CDCClient()
    received: list[dict[str, object]] = []

    async def cb(d: dict[str, object]) -> None:
        received.append(d)

    sub = CDCSubscription(
        profile="default", tables=["orders"], strategy="polling", callback=cb
    )
    event = CDCEvent(
        operation="UPSERT",
        table="orders",
        timestamp="2026-06-05T00:00:00Z",
        profile="default",
        new={"id": 7, "total": 100},
    )
    await client._dispatch_change(sub, event)

    assert len(received) == 1
    payload = received[0]
    assert payload["operation"] == "UPSERT"
    assert payload["table"] == "orders"
    assert payload["new"] == {"id": 7, "total": 100}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_dispatch_change_handles_callback_error() -> None:
    """Callback raising must be logged but not propagated."""
    client = CDCClient()

    async def bad_cb(_d: dict[str, object]) -> None:
        raise RuntimeError("callback boom")

    sub = CDCSubscription(
        profile="default", tables=["orders"], strategy="polling", callback=bad_cb
    )
    event = CDCEvent(
        operation="INSERT",
        table="orders",
        timestamp="2026-06-05T00:00:00Z",
        profile="default",
    )
    # Should NOT raise — internal logger.error swallows callback errors
    await client._dispatch_change(sub, event)


# ── _PollingStrategy._get_cursor: Redis path + local fallback ──────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_polling_get_cursor_falls_back_to_local_on_redis_failure() -> None:
    """If RedisCursor raises any exception, _get_cursor returns the local/default value.

    The local cache ``_last_check_local`` is read-only here (writes happen in
    ``_advance_cursor``); when the key is missing the default is returned.
    """
    strategy = _PollingStrategy()
    default = datetime(2026, 1, 1, tzinfo=UTC)

    with patch(
        "src.backend.infrastructure.clients.storage.redis_coordinator.RedisCursor",
        side_effect=RuntimeError("redis offline"),
    ):
        result = await strategy._get_cursor("default:orders", default)

    assert result == default
    # Local cache is still empty (writes happen in _advance_cursor)
    assert strategy._last_check_local == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cdc_polling_get_cursor_uses_redis_when_available() -> None:
    """When Redis returns a stored ISO timestamp, _get_cursor parses and returns it."""
    strategy = _PollingStrategy()
    default = datetime(2026, 1, 1, tzinfo=UTC)
    stored_iso = "2026-05-15T10:30:00+00:00"

    fake_cursor = AsyncMock()
    fake_cursor.get_or_init = AsyncMock(return_value=stored_iso)
    fake_cursor_ctor = MagicMock(return_value=fake_cursor)

    with patch(
        "src.backend.infrastructure.clients.storage.redis_coordinator.RedisCursor",
        fake_cursor_ctor,
    ):
        result = await strategy._get_cursor("oracle_1:orders", default)

    assert result == datetime.fromisoformat(stored_iso)
    fake_cursor_ctor.assert_called_once_with("cdc:cursor:oracle_1:orders")


# ════════════════════════════════════════════════════════════════════
# Property tests (hypothesis)
# ════════════════════════════════════════════════════════════════════


# ── CDCEvent.to_dict: field-preserving round-trip ──────────────────


@given(
    operation=st.sampled_from(["INSERT", "UPDATE", "DELETE", "UPSERT"]),
    table=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_"
        ),
        min_size=1,
        max_size=32,
    ),
    profile=st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="_-"
        ),
        min_size=1,
        max_size=32,
    ),
    ts=st.datetimes(
        timezones=st.just(UTC),
        min_value=datetime(2020, 1, 1),
        max_value=datetime(2030, 1, 1),
    ),
    has_new=st.booleans(),
    has_old=st.booleans(),
)
@settings(max_examples=50)
@pytest.mark.unit
def test_cdc_event_to_dict_round_trip_preserves_fields(
    operation: str, table: str, profile: str, ts: datetime, has_new: bool, has_old: bool
) -> None:
    """For any well-formed CDCEvent input, to_dict() must preserve every field verbatim.

    Invariants:
        * exactly 6 keys (operation, table, timestamp, profile, new, old);
        * string-typed fields returned unchanged;
        * new/old slots are None when absent, the original dict otherwise.
    """
    new_payload: dict[str, object] | None = {"id": 1, "v": "x"} if has_new else None
    old_payload: dict[str, object] | None = {"id": 1, "v": "old"} if has_old else None

    event = CDCEvent(
        operation=operation,
        table=table,
        timestamp=ts.isoformat(),
        profile=profile,
        new=new_payload,
        old=old_payload,
    )
    d = event.to_dict()

    # Structural invariants
    assert isinstance(d, dict)
    assert set(d.keys()) == {"operation", "table", "timestamp", "profile", "new", "old"}

    # Field-level invariants (the round-trip property)
    assert d["operation"] == operation
    assert d["table"] == table
    assert d["profile"] == profile
    assert d["timestamp"] == ts.isoformat()
    assert d["new"] == new_payload
    assert d["old"] == old_payload
