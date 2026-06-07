"""Unit tests для pydash-based EIP processors (Sprint 57 W2).

Coverage:
* PydashGetProcessor — 4 tests
* PydashSetProcessor — 3 tests
* PydashOmitProcessor — 3 tests
* PydashPickProcessor — 2 tests
* PydashMergeProcessor — 3 tests
"""

from __future__ import annotations

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.dict_ops import (
    PydashGetProcessor,
    PydashMergeProcessor,
    PydashOmitProcessor,
    PydashPickProcessor,
    PydashSetProcessor,
)


def _exchange(body: object = "", headers: dict | None = None) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg)


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── PydashGetProcessor ──────────────────────────────────────────────


class TestPydashGet:
    @pytest.mark.asyncio
    async def test_simple_path(self) -> None:
        """Simple path extracted with default fallback."""
        op = PydashGetProcessor(path="customer.email", default="unknown")
        ex = _exchange({"customer": {"email": "a@b.com"}})
        await op.process(ex, _ctx())
        assert ex.get_property("extracted_value") == "a@b.com"

    @pytest.mark.asyncio
    async def test_missing_path_returns_default(self) -> None:
        """Missing path → default value в property."""
        op = PydashGetProcessor(path="customer.email", default="anonymous")
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property("extracted_value") == "anonymous"

    @pytest.mark.asyncio
    async def test_nested_path_with_list(self) -> None:
        """Bracket notation для list access."""
        op = PydashGetProcessor(path="users[0].name")
        ex = _exchange({"users": [{"name": "alice"}, {"name": "bob"}]})
        await op.process(ex, _ctx())
        assert ex.get_property("extracted_value") == "alice"

    @pytest.mark.asyncio
    async def test_write_back(self) -> None:
        """write_back=True → out_message body = extracted value, in_message body unchanged."""
        op = PydashGetProcessor(path="id", write_back=True)
        ex = _exchange({"id": 42, "extra": "ignored"})
        await op.process(ex, _ctx())
        # in_message.body НЕ модифицируется (immutability), out_message = extracted value
        assert ex.in_message.body == {"id": 42, "extra": "ignored"}
        assert ex.out_message is not None
        assert ex.out_message.body == 42

    def test_path_required(self) -> None:
        """Empty path → ValueError at construction."""
        with pytest.raises(ValueError, match="path is required"):
            PydashGetProcessor(path="")


# ── PydashSetProcessor ──────────────────────────────────────────────


class TestPydashSet:
    @pytest.mark.asyncio
    async def test_set_simple(self) -> None:
        """Set simple path на empty body."""
        op = PydashSetProcessor(path="metadata.source", value="api_v2")
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"metadata": {"source": "api_v2"}}

    @pytest.mark.asyncio
    async def test_set_preserves_existing(self) -> None:
        """Set не затирает existing keys на других paths."""
        op = PydashSetProcessor(path="metadata.source", value="api_v2")
        ex = _exchange({"metadata": {"version": 1}, "id": "x"})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        body = ex.out_message.body
        assert body["id"] == "x"
        assert body["metadata"]["version"] == 1
        assert body["metadata"]["source"] == "api_v2"

    @pytest.mark.asyncio
    async def test_set_with_callable_value(self) -> None:
        """Callable value → вызывается с exchange для dynamic value."""
        op = PydashSetProcessor(
            path="metadata.timestamp",
            value=lambda ex: ex.get_property("now") or "fallback",
        )
        ex = _exchange({})
        ex.set_property("now", "2025-06-01T00:00:00Z")
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {
            "metadata": {"timestamp": "2025-06-01T00:00:00Z"}
        }


# ── PydashOmitProcessor ─────────────────────────────────────────────


class TestPydashOmit:
    @pytest.mark.asyncio
    async def test_top_level_omit(self) -> None:
        """Top-level keys removed."""
        op = PydashOmitProcessor(fields=["password", "ssn"])
        ex = _exchange(
            {"name": "alice", "email": "a@b.com", "password": "x", "ssn": "123"}
        )
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"name": "alice", "email": "a@b.com"}

    @pytest.mark.asyncio
    async def test_deep_omit(self) -> None:
        """deep=True → recursive removal на любой глубине."""
        op = PydashOmitProcessor(fields=["secret"], deep=True)
        ex = _exchange(
            {
                "user": {"name": "alice", "secret": "hidden"},
                "metadata": {"secret": "also-hidden", "version": 1},
            }
        )
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        body = ex.out_message.body
        assert "secret" not in body["user"]
        assert "secret" not in body["metadata"]
        assert body["user"]["name"] == "alice"
        assert body["metadata"]["version"] == 1

    @pytest.mark.asyncio
    async def test_non_dict_body_noop(self) -> None:
        """Non-dict body → no-op + warning."""
        op = PydashOmitProcessor(fields=["x"])
        ex = _exchange("just a string")
        await op.process(ex, _ctx())
        # body unchanged
        assert ex.in_message.body == "just a string"

    def test_fields_required(self) -> None:
        """Empty fields → ValueError."""
        with pytest.raises(ValueError, match="fields must be non-empty"):
            PydashOmitProcessor(fields=[])


# ── PydashPickProcessor ─────────────────────────────────────────────


class TestPydashPick:
    @pytest.mark.asyncio
    async def test_pick_whitelist(self) -> None:
        """Output содержит только whitelisted fields."""
        op = PydashPickProcessor(fields=["id", "name", "email"])
        ex = _exchange(
            {
                "id": 1,
                "name": "alice",
                "email": "a@b.com",
                "password": "x",
                "ssn": "123",
            }
        )
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"id": 1, "name": "alice", "email": "a@b.com"}

    def test_fields_required(self) -> None:
        """Empty fields → ValueError."""
        with pytest.raises(ValueError, match="fields must be non-empty"):
            PydashPickProcessor(fields=[])


# ── PydashMergeProcessor ───────────────────────────────────────────


class TestPydashMerge:
    @pytest.mark.asyncio
    async def test_merge_fills_missing(self) -> None:
        """Defaults заполняют missing keys, body values сохраняются."""
        op = PydashMergeProcessor(
            defaults={
                "audit": {"source": "api_v2", "version": 1},
                "metadata": {"retries": 0},
            }
        )
        ex = _exchange({"audit": {"version": 2}})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        body = ex.out_message.body
        assert body["audit"]["version"] == 2  # body wins
        assert body["audit"]["source"] == "api_v2"  # default filled
        assert body["metadata"]["retries"] == 0  # default added

    @pytest.mark.asyncio
    async def test_merge_overwrite(self) -> None:
        """overwrite=True → defaults перезаписывают body values."""
        op = PydashMergeProcessor(defaults={"audit": {"version": 99}}, overwrite=True)
        ex = _exchange({"audit": {"version": 1}})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"audit": {"version": 99}}

    @pytest.mark.asyncio
    async def test_merge_non_dict_body(self) -> None:
        """Non-dict body → defaults copy как new body."""
        op = PydashMergeProcessor(defaults={"x": 1})
        ex = _exchange("string body")
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"x": 1}

    def test_defaults_must_be_dict(self) -> None:
        """defaults not dict → ValueError."""
        with pytest.raises(ValueError, match="defaults must be a dict"):
            PydashMergeProcessor(defaults="not a dict")  # type: ignore[arg-type]
