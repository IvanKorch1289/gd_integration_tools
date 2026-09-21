"""Unit tests for the infrastructure-client Protocols in ``core.interfaces.integrations``.

Wave 6.4 introduced 10 ``@runtime_checkable`` Protocols describing the
public surface that ``services/{io,ops,integrations,execution}`` may rely on,
without importing ``infrastructure.*`` directly. These tests cover:

* The 10 Protocols (browser, ClickHouse, SMTP, eXpress, Redis KV, scheduler,
  external session, HMAC signatures, caching decorator, connector config store).
* Each Protocol's contract: ``isinstance`` conformance, missing-method rejection,
  and behavioural round-trip on a minimal fake implementation.
* The ``@runtime_checkable`` decoration (Protocols are checkable at runtime).
* Module-level surface (``__all__``).

Reference implementation: ``src/backend/core/interfaces/integrations.py``.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.interfaces.integrations import (
    BrowserClientProtocol,
    CachingDecoratorProtocol,
    ClickHouseClientProtocol,
    ConnectorConfigStoreProtocol,
    ExpressClientProtocol,
    ExternalSessionManagerProtocol,
    RedisKeyValueClientProtocol,
    SchedulerManagerProtocol,
    SignatureBuilderProtocol,
    SmtpClientProtocol,
)

# ----------------------------------------------------------------------
# Fake implementations
# ----------------------------------------------------------------------


class _FakeBrowser:
    """Implements all 7 ``BrowserClientProtocol`` methods."""

    async def navigate(self, url: str) -> dict[str, Any]:
        return {"url": url, "status": 200}

    async def click(self, url: str, selector: str) -> dict[str, Any]:
        return {"url": url, "selector": selector, "clicked": True}

    async def fill_form(
        self, url: str, fields: dict[str, str], submit: str | None = None
    ) -> dict[str, Any]:
        return {"url": url, "fields": fields, "submit": submit}

    async def extract_text(self, url: str, selector: str) -> list[str]:
        return [f"text-from-{url}"]

    async def extract_table(self, url: str, selector: str) -> list[dict[str, str]]:
        return [{"col1": "v1", "col2": "v2"}]

    async def screenshot(self, url: str) -> bytes:
        return b"\x89PNG\r\n\x1a\n-fake-screenshot-"

    async def run_scenario(self, steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{"step": i, "ok": True} for i, _ in enumerate(steps)]


class _FakeClickHouse:
    """Implements ``ClickHouseClientProtocol`` (4 async methods)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def query(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        self.calls.append(("query", sql[:16], str(params)))
        return [{"x": 1}]

    async def insert(self, table: str, rows: list[dict[str, Any]]) -> int:
        self.calls.append(("insert", table, str(len(rows))))
        return len(rows)

    async def aggregate(
        self,
        table: str,
        agg_func: str,
        column: str,
        group_by: str | None = None,
        where: str | None = None,
    ) -> list[dict[str, Any]]:
        self.calls.append(("aggregate", table, agg_func, column))
        return [{"agg": 42}]

    async def ping(self) -> bool:
        self.calls.append(("ping",))
        return True


class _FakeSmtp:
    """Implements ``SmtpClientProtocol`` (2 async methods)."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_email(
        self,
        to: Any,
        subject: str,
        body: str,
        content_type: str = "text/plain",
        **kwargs: Any,
    ) -> Any:
        record = {
            "to": to,
            "subject": subject,
            "body": body,
            "content_type": content_type,
        }
        record.update(kwargs)
        self.sent.append(record)
        return {"msg_id": f"smtp-{len(self.sent)}"}

    async def test_connection(self) -> bool:
        return True


class _FakeExpress:
    """Implements ``ExpressClientProtocol`` (4 async methods)."""

    async def send_message(self, chat_id: str, text: str) -> dict[str, Any]:
        return {"chat_id": chat_id, "echo": text, "ok": True}

    async def send_direct(self, user_huid: str, text: str) -> dict[str, Any]:
        return {"user_huid": user_huid, "echo": text}

    async def send_notification(
        self, group_chat_ids: list[str], text: str
    ) -> dict[str, Any]:
        return {"delivered_to": group_chat_ids, "text": text}

    async def create_chat(
        self,
        name: str,
        members: list[str],
        description: str = "",
        chat_type: str = "group_chat",
    ) -> dict[str, Any]:
        return {
            "name": name,
            "members": members,
            "description": description,
            "chat_type": chat_type,
        }


class _FakeRedisKV:
    """Implements ``RedisKeyValueClientProtocol`` (3 async + 1 sync)."""

    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.calls: list[tuple[str, ...]] = []

    async def set(
        self, key: str, value: Any, ex: int | None = None, **kwargs: Any
    ) -> Any:
        self.calls.append(("set", key))
        self.store[key] = value
        return True

    async def get(self, key: str) -> Any:
        self.calls.append(("get", key))
        return self.store.get(key)

    async def delete(self, *keys: str) -> int:
        self.calls.append(("delete", *keys))
        removed = 0
        for k in keys:
            if k in self.store:
                self.store.pop(k, None)
                removed += 1
        return removed

    def scan_iter(self, match: str | None = None, **kwargs: Any) -> Any:
        self.calls.append(("scan_iter", str(match)))
        return iter(self.store.keys())


class _FakeScheduler:
    """Implements ``SchedulerManagerProtocol`` (one property)."""

    @property
    def scheduler(self) -> Any:
        return object()


class _FakeAsyncContextManager:
    """Minimal async context manager that yields a fixed value on ``__aenter__``."""

    def __init__(self, value: Any) -> None:
        self._value = value

    async def __aenter__(self) -> Any:
        return self._value

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        return None


class _FakeExternalSession:
    """Implements ``ExternalSessionManagerProtocol`` (one async-cm method)."""

    @staticmethod
    def create_session() -> Any:
        return _FakeAsyncContextManager({"session": "fake"})


def _fake_signature(
    payload: dict[str, Any] | bytes | str, secret: str
) -> dict[str, str]:
    return {"X-Sig": f"hmac:{len(str(payload))}:{len(secret)}"}


def _fake_caching_decorator(func: Any) -> Any:
    """Trivially pass-through (real impl is in ``infrastructure.decorators``)."""
    return func


class _FakeConnectorConfigStore:
    """Implements ``ConnectorConfigStoreProtocol`` (4 async methods)."""

    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    async def get(self, name: str) -> Any:
        return self._items.get(name)

    async def save(
        self,
        name: str,
        config: dict[str, Any],
        enabled: bool = True,
        user: str | None = None,
    ) -> Any:
        self._items[name] = {
            "name": name,
            "config": config,
            "enabled": enabled,
            "user": user,
        }
        return self._items[name]

    async def list_all(self) -> list[Any]:
        return list(self._items.values())

    async def delete(self, name: str) -> bool:
        return self._items.pop(name, None) is not None


# ----------------------------------------------------------------------
# Module-level surface
# ----------------------------------------------------------------------


def test_integration_imports() -> None:
    """All 10 protocols are importable from the module."""
    from src.backend.core.interfaces import integrations as mod

    assert mod.BrowserClientProtocol is not None
    assert mod.ClickHouseClientProtocol is not None
    assert mod.SmtpClientProtocol is not None
    assert mod.ExpressClientProtocol is not None
    assert mod.RedisKeyValueClientProtocol is not None
    assert mod.SchedulerManagerProtocol is not None
    assert mod.ExternalSessionManagerProtocol is not None
    assert mod.SignatureBuilderProtocol is not None
    assert mod.CachingDecoratorProtocol is not None
    assert mod.ConnectorConfigStoreProtocol is not None


def test_dunder_all_exports() -> None:
    """``__all__`` lists exactly the 10 documented protocol names."""
    from src.backend.core.interfaces import integrations as mod

    assert set(mod.__all__) == {
        "BrowserClientProtocol",
        "CachingDecoratorProtocol",
        "ClickHouseClientProtocol",
        "ConnectorConfigStoreProtocol",
        "ExpressClientProtocol",
        "ExternalSessionManagerProtocol",
        "RedisKeyValueClientProtocol",
        "SchedulerManagerProtocol",
        "SignatureBuilderProtocol",
        "SmtpClientProtocol",
    }


# ----------------------------------------------------------------------
# Per-Protocol runtime_checkable conformance
# ----------------------------------------------------------------------


def test_browser_protocol_is_runtime_checkable() -> None:
    """``BrowserClientProtocol`` is ``@runtime_checkable`` and accepts a full fake."""
    assert isinstance(_FakeBrowser(), BrowserClientProtocol)


def test_browser_protocol_rejects_incomplete() -> None:
    """A class missing any of the 7 browser methods must not satisfy the Protocol."""

    class _BadBrowser:
        async def navigate(self, url: str) -> dict[str, Any]:
            return {}

    assert not isinstance(_BadBrowser(), BrowserClientProtocol)


def test_clickhouse_protocol_is_runtime_checkable() -> None:
    """``ClickHouseClientProtocol`` accepts a full fake."""
    assert isinstance(_FakeClickHouse(), ClickHouseClientProtocol)


def test_smtp_protocol_is_runtime_checkable() -> None:
    """``SmtpClientProtocol`` accepts a full fake."""
    assert isinstance(_FakeSmtp(), SmtpClientProtocol)


def test_express_protocol_is_runtime_checkable() -> None:
    """``ExpressClientProtocol`` accepts a full fake."""
    assert isinstance(_FakeExpress(), ExpressClientProtocol)


def test_redis_kv_protocol_is_runtime_checkable() -> None:
    """``RedisKeyValueClientProtocol`` accepts a full fake (sync + async methods)."""
    assert isinstance(_FakeRedisKV(), RedisKeyValueClientProtocol)


def test_scheduler_protocol_is_runtime_checkable() -> None:
    """``SchedulerManagerProtocol`` accepts a fake exposing the ``scheduler`` property."""
    assert isinstance(_FakeScheduler(), SchedulerManagerProtocol)


def test_external_session_protocol_is_runtime_checkable() -> None:
    """``ExternalSessionManagerProtocol`` accepts a fake with ``create_session``."""
    assert isinstance(_FakeExternalSession(), ExternalSessionManagerProtocol)


def test_signature_protocol_is_runtime_checkable() -> None:
    """``SignatureBuilderProtocol`` is ``__call__``-shaped and accepts a plain function."""
    assert isinstance(_fake_signature, SignatureBuilderProtocol)


def test_caching_protocol_is_runtime_checkable() -> None:
    """``CachingDecoratorProtocol`` is ``__call__``-shaped and accepts a function."""
    assert isinstance(_fake_caching_decorator, CachingDecoratorProtocol)


def test_connector_config_store_protocol_is_runtime_checkable() -> None:
    """``ConnectorConfigStoreProtocol`` accepts a full fake store."""
    assert isinstance(_FakeConnectorConfigStore(), ConnectorConfigStoreProtocol)


def test_abc_protocols_cannot_instantiate() -> None:
    """Runtime-checkable Protocols raise on direct instantiation."""
    with pytest.raises(TypeError):
        BrowserClientProtocol()  # type: ignore[call-arg]


def test_concrete_implementation_required() -> None:
    """A bare subclass with no methods fails isinstance for every Protocol."""

    class _Empty:
        pass

    for proto in (
        BrowserClientProtocol,
        ClickHouseClientProtocol,
        SmtpClientProtocol,
        ExpressClientProtocol,
        RedisKeyValueClientProtocol,
        SchedulerManagerProtocol,
        ExternalSessionManagerProtocol,
        ConnectorConfigStoreProtocol,
    ):
        assert not isinstance(_Empty(), proto), f"{proto.__name__} accepted _Empty"


# ----------------------------------------------------------------------
# Behavioural round-trips
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_screenshot_returns_bytes() -> None:
    """``screenshot(url)`` returns raw bytes (PNG signature in fake)."""
    browser = _FakeBrowser()
    blob = await browser.screenshot("https://example.com")
    assert isinstance(blob, bytes)
    assert blob.startswith(b"\x89PNG")


@pytest.mark.asyncio
async def test_clickhouse_query_insert_ping() -> None:
    """``query`` / ``insert`` / ``ping`` return expected shapes; call log records order."""
    ch = _FakeClickHouse()
    rows = await ch.query("SELECT 1")
    assert rows == [{"x": 1}]
    n = await ch.insert("events", [{"a": 1}, {"a": 2}])
    assert n == 2
    assert await ch.ping() is True
    assert [c[0] for c in ch.calls] == ["query", "insert", "ping"]


@pytest.mark.asyncio
async def test_smtp_send_email_records_message() -> None:
    """``send_email`` records the message; ``test_connection`` returns True."""
    smtp = _FakeSmtp()
    result = await smtp.send_email(
        to=["a@example.com"], subject="hi", body="hello", content_type="text/html"
    )
    assert result["msg_id"] == "smtp-1"
    assert smtp.sent[0]["subject"] == "hi"
    assert smtp.sent[0]["content_type"] == "text/html"
    assert await smtp.test_connection() is True


@pytest.mark.asyncio
async def test_express_send_and_create() -> None:
    """``send_message`` / ``create_chat`` propagate the structured fields."""
    express = _FakeExpress()
    out = await express.send_message("chat-1", "ping")
    assert out["chat_id"] == "chat-1"
    assert out["echo"] == "ping"

    chat = await express.create_chat(
        name="dev", members=["u1", "u2"], description="team chat"
    )
    assert chat["name"] == "dev"
    assert chat["members"] == ["u1", "u2"]
    assert chat["chat_type"] == "group_chat"  # default


@pytest.mark.asyncio
async def test_redis_kv_set_get_delete_scan() -> None:
    """``set``/``get``/``delete``/``scan_iter`` round-trip with recorded calls."""
    redis = _FakeRedisKV()
    await redis.set("k1", "v1", ex=60)
    assert await redis.get("k1") == "v1"
    assert await redis.delete("k1") == 1
    assert await redis.get("k1") is None
    # scan_iter is a sync generator over the (now empty) store.
    assert list(redis.scan_iter(match="*")) == []


@pytest.mark.asyncio
async def test_external_session_async_context_manager() -> None:
    """``create_session()`` returns an async context manager yielding a session."""
    mgr = _FakeExternalSession()
    cm = mgr.create_session()
    assert hasattr(cm, "__aenter__") and hasattr(cm, "__aexit__")
    async with cm as session:
        assert session == {"session": "fake"}


def test_signature_builder_call_shape() -> None:
    """``SignatureBuilderProtocol`` is callable and returns a header dict."""
    out = _fake_signature({"a": 1}, "secret-key")
    assert isinstance(out, dict)
    assert "X-Sig" in out
    assert out["X-Sig"].startswith("hmac:")


def test_caching_decorator_returns_callable() -> None:
    """``CachingDecoratorProtocol`` wraps a function and returns a callable."""

    @_fake_caching_decorator
    def add(a: int, b: int) -> int:
        return a + b

    assert add(1, 2) == 3


@pytest.mark.asyncio
async def test_connector_config_store_save_list_get_delete() -> None:
    """``save`` → ``list_all`` → ``get`` → ``delete`` round-trip on the fake store."""
    store = _FakeConnectorConfigStore()
    saved = await store.save("acme-erp", {"url": "https://erp"}, user="admin")
    assert saved["name"] == "acme-erp"
    assert saved["enabled"] is True

    all_items = await store.list_all()
    assert len(all_items) == 1
    assert all_items[0]["name"] == "acme-erp"

    fetched = await store.get("acme-erp")
    assert fetched["config"] == {"url": "https://erp"}

    assert await store.delete("acme-erp") is True
    assert await store.get("acme-erp") is None


# ----------------------------------------------------------------------
# Integration: multiple Protocols co-exist (no name collisions)
# ----------------------------------------------------------------------


def test_no_protocol_name_collision() -> None:
    """All 10 protocols have unique class names (sanity check)."""
    from src.backend.core.interfaces import integrations as mod

    names = [
        mod.BrowserClientProtocol.__name__,
        mod.ClickHouseClientProtocol.__name__,
        mod.SmtpClientProtocol.__name__,
        mod.ExpressClientProtocol.__name__,
        mod.RedisKeyValueClientProtocol.__name__,
        mod.SchedulerManagerProtocol.__name__,
        mod.ExternalSessionManagerProtocol.__name__,
        mod.SignatureBuilderProtocol.__name__,
        mod.CachingDecoratorProtocol.__name__,
        mod.ConnectorConfigStoreProtocol.__name__,
    ]
    assert len(names) == len(set(names))


def test_protocols_all_runtime_checkable_decorated() -> None:
    """All 10 Protocols are decorated ``@runtime_checkable`` (have ``_is_runtime_protocol``)."""
    from src.backend.core.interfaces import integrations as mod

    for proto in (
        mod.BrowserClientProtocol,
        mod.ClickHouseClientProtocol,
        mod.SmtpClientProtocol,
        mod.ExpressClientProtocol,
        mod.RedisKeyValueClientProtocol,
        mod.SchedulerManagerProtocol,
        mod.ExternalSessionManagerProtocol,
        mod.SignatureBuilderProtocol,
        mod.CachingDecoratorProtocol,
        mod.ConnectorConfigStoreProtocol,
    ):
        # ``runtime_checkable`` Protocols set ``_is_runtime_protocol`` to True.
        assert getattr(proto, "_is_runtime_protocol", False) is True, (
            f"{proto.__name__} is not @runtime_checkable"
        )
