"""Unit tests for generic DSL processors."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.generic import (
    AbTestRouterProcessor,
    BulkheadProcessor,
    FeatureFlagGuardProcessor,
    LineageTrackerProcessor,
    SchemaValidateProcessor,
    ShadowModeProcessor,
    SseSourceProcessor,
)


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


class TestShadowModeProcessor:
    @pytest.mark.asyncio
    async def test_sets_shadow_flag(self) -> None:
        proc = ShadowModeProcessor([])
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties.get("shadow_mode") is False  # restored after

    @pytest.mark.asyncio
    async def test_restores_previous_value(self) -> None:
        proc = ShadowModeProcessor([])
        exchange = _ex({})
        exchange.set_property("shadow_mode", True)
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["shadow_mode"] is True


class TestBulkheadProcessor:
    def test_init_limit_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="limit должен быть"):
            BulkheadProcessor("test", 0, [])

    @pytest.mark.asyncio
    async def test_acquire_and_run(self) -> None:
        proc = BulkheadProcessor("test", 2, [])
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_no_wait_locked(self) -> None:
        proc = BulkheadProcessor("test2", 1, [], wait=False)
        exchange = _ex({})
        # Lock the semaphore manually
        sem = proc._get_semaphore()
        await sem.acquire()
        with pytest.raises(RuntimeError, match="исчерпан"):
            await proc.process(exchange, None)  # type: ignore[arg-type]
        sem.release()


class TestLineageTrackerProcessor:
    @pytest.mark.asyncio
    async def test_tracks_lineage(self) -> None:
        proc = LineageTrackerProcessor(tag="step1")
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        lineage = exchange.properties.get("_lineage")
        assert len(lineage) == 1
        assert lineage[0]["tag"] == "step1"


class TestSseSourceProcessor:
    @pytest.mark.asyncio
    async def test_sets_properties(self) -> None:
        proc = SseSourceProcessor("https://example.com/events", ["order"])
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["sse_url"] == "https://example.com/events"
        assert exchange.properties["sse_event_types"] == ["order"]


class TestSchemaValidateProcessor:
    @pytest.mark.asyncio
    async def test_valid_object(self) -> None:
        proc = SchemaValidateProcessor({"type": "object", "required": ["name"]})
        exchange = _ex({"name": "Alice"})
        await proc.process(exchange, None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_type_mismatch(self) -> None:
        proc = SchemaValidateProcessor({"type": "object"})
        exchange = _ex("not an object")
        with pytest.raises(Exception):
            await proc.process(exchange, None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_missing_required(self) -> None:
        proc = SchemaValidateProcessor({"type": "object", "required": ["name"]})
        exchange = _ex({})
        with pytest.raises(Exception):
            await proc.process(exchange, None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_fallback_path(self) -> None:
        proc = SchemaValidateProcessor({"type": "object"})
        proc._strict = False
        exchange = _ex("not an object")
        with pytest.raises(ValueError, match="must be object"):
            await proc.process(exchange, None)  # type: ignore[arg-type]


class TestAbTestRouterProcessor:
    def test_split_percent_invalid(self) -> None:
        with pytest.raises(ValueError, match="0..100"):
            AbTestRouterProcessor([], [], split_percent=101)

    @pytest.mark.asyncio
    async def test_routes_to_variant(self) -> None:
        proc = AbTestRouterProcessor([], [], split_percent=50)
        exchange = _ex({})
        exchange.meta.exchange_id = "test-id"
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["ab_variant"] in ("A", "B")


class TestFeatureFlagGuardProcessor:
    @pytest.mark.asyncio
    async def test_disabled_flag_skips(self) -> None:
        proc = FeatureFlagGuardProcessor("flag1", [])
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert "flag1" not in exchange.properties

    @pytest.mark.asyncio
    async def test_enabled_flag_runs(self) -> None:
        proc = FeatureFlagGuardProcessor("flag1", [], resolver=lambda f: True)
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]

    @pytest.mark.asyncio
    async def test_resolver_exception(self) -> None:
        proc = FeatureFlagGuardProcessor(
            "flag1", [], resolver=lambda f: (_ for _ in ()).throw(RuntimeError("fail"))
        )
        exchange = _ex({})
        await proc.process(exchange, None)  # type: ignore[arg-type]
