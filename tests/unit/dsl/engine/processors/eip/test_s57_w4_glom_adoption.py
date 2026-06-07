"""Unit tests для glom-based EIP processors (Sprint 57 W4).

Coverage:
* GlomExtractProcessor — 5 tests (Coalesce fallback chain, Path programmatic,
  default, write_back, missing path)
* GlomTransformProcessor — 4 tests (basic, missing path, skip_missing=False,
  nested paths)
* GlomFlattenProcessor — 4 tests (basic, custom separator, max_depth, skip_empty)
"""

from __future__ import annotations

import pytest
from glom import Path

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.glom_ops import (
    GlomExtractProcessor,
    GlomFlattenProcessor,
    GlomTransformProcessor,
)


def _exchange(body: object = "", headers: dict | None = None) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg)


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── GlomExtractProcessor ────────────────────────────────────────────


class TestGlomExtract:
    @pytest.mark.asyncio
    async def test_first_path_match(self) -> None:
        """First matching path wins (Coalesce semantics)."""
        op = GlomExtractProcessor(
            paths=["customer.email", "user.email"], default="unknown"
        )
        ex = _exchange({"customer": {"email": "a@b.com"}})
        await op.process(ex, _ctx())
        assert ex.get_property("glom_extracted") == "a@b.com"

    @pytest.mark.asyncio
    async def test_fallback_to_second_path(self) -> None:
        """If first path miss → try second."""
        op = GlomExtractProcessor(
            paths=["customer.email", "user.email"], default="unknown"
        )
        ex = _exchange({"user": {"email": "u@x.com"}})
        await op.process(ex, _ctx())
        assert ex.get_property("glom_extracted") == "u@x.com"

    @pytest.mark.asyncio
    async def test_default_when_all_paths_miss(self) -> None:
        """All paths miss → default value."""
        op = GlomExtractProcessor(
            paths=["customer.email", "user.email"], default="anonymous@example.com"
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property("glom_extracted") == "anonymous@example.com"

    @pytest.mark.asyncio
    async def test_programmatic_path(self) -> None:
        """Path instance вместо string."""
        op = GlomExtractProcessor(
            paths=[Path("customer", "email"), Path("user", "email")], default="x"
        )
        ex = _exchange({"customer": {"email": "a@b"}})
        await op.process(ex, _ctx())
        assert ex.get_property("glom_extracted") == "a@b"

    @pytest.mark.asyncio
    async def test_write_back(self) -> None:
        """write_back=True → out_message body = extracted value."""
        op = GlomExtractProcessor(
            paths=["customer.email"], default="x", write_back=True
        )
        ex = _exchange({"customer": {"email": "a@b"}})
        await op.process(ex, _ctx())
        assert ex.in_message.body == {"customer": {"email": "a@b"}}
        assert ex.out_message is not None
        assert ex.out_message.body == "a@b"

    def test_paths_required(self) -> None:
        """Empty paths → ValueError."""
        with pytest.raises(ValueError, match="paths must be non-empty"):
            GlomExtractProcessor(paths=[])


# ── GlomTransformProcessor ──────────────────────────────────────────


class TestGlomTransform:
    @pytest.mark.asyncio
    async def test_basic_reshape(self) -> None:
        """Body reshaped according to spec mapping."""
        op = GlomTransformProcessor(
            spec={"user_id": "id", "name": "profile.full_name", "tags": "metadata.tags"}
        )
        ex = _exchange(
            {
                "id": 1,
                "profile": {"full_name": "Alice"},
                "metadata": {"tags": ["x", "y"]},
                "password": "secret",  # not in spec → excluded
            }
        )
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {
            "user_id": 1,
            "name": "Alice",
            "tags": ["x", "y"],
        }

    @pytest.mark.asyncio
    async def test_missing_path_with_skip(self) -> None:
        """skip_missing=True (default) → missing source → default value."""
        op = GlomTransformProcessor(
            spec={"name": "profile.full_name", "age": "profile.age"}, default=None
        )
        ex = _exchange({"profile": {"full_name": "Alice"}})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"name": "Alice", "age": None}

    @pytest.mark.asyncio
    async def test_missing_path_without_skip(self) -> None:
        """skip_missing=False → missing keys НЕ appear в output (если default не задан)."""
        # NOTE: чтобы действительно "skip" missing, default НЕ передаём
        # (glom raises Miss → continue).
        op = GlomTransformProcessor(
            spec={"name": "profile.full_name", "age": "profile.age"}, skip_missing=False
        )
        ex = _exchange({"profile": {"full_name": "Alice"}})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"name": "Alice"}  # no "age" key

    def test_spec_required(self) -> None:
        """Empty spec → ValueError."""
        with pytest.raises(ValueError, match="spec must be non-empty"):
            GlomTransformProcessor(spec={})


# ── GlomFlattenProcessor ────────────────────────────────────────────


class TestGlomFlatten:
    @pytest.mark.asyncio
    async def test_basic_flatten(self) -> None:
        """Nested dict → single-level with dot-keys."""
        op = GlomFlattenProcessor()
        ex = _exchange({"user": {"profile": {"name": "Alice"}}, "id": 1})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"user.profile.name": "Alice", "id": 1}

    @pytest.mark.asyncio
    async def test_custom_separator(self) -> None:
        """Custom separator (e.g., '_' для SQL column names)."""
        op = GlomFlattenProcessor(separator="_")
        ex = _exchange({"a": {"b": {"c": 1}}})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        assert ex.out_message.body == {"a_b_c": 1}

    @pytest.mark.asyncio
    async def test_max_depth(self) -> None:
        """max_depth=2 → recurse 2 levels, остановить на 3-м (uses default '.' separator).

        depth=0 (root) → recurse, depth=1 (a.b) → recurse, depth=2 (a.b.c) → stop.
        """
        op = GlomFlattenProcessor(max_depth=2)
        ex = _exchange({"a": {"b": {"c": {"d": 1}}}})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        # a.b.c — 3 levels traversed (root + 2 recursions), c's value kept as-is
        assert ex.out_message.body == {"a.b.c": {"d": 1}}

    @pytest.mark.asyncio
    async def test_skip_empty(self) -> None:
        """skip_empty=True (default) → empty dicts/lists NOT included."""
        op = GlomFlattenProcessor(skip_empty=True)
        ex = _exchange({"a": {}, "b": [], "c": 0, "d": "value", "e": ""})
        await op.process(ex, _ctx())
        assert ex.out_message is not None
        # a={} и b=[] excluded; c=0, d="value" included; e="" excluded (empty str)
        assert "a" not in ex.out_message.body
        assert "b" not in ex.out_message.body
        assert ex.out_message.body["c"] == 0  # 0 is NOT "empty" (only literal empty)
        assert ex.out_message.body["d"] == "value"

    @pytest.mark.asyncio
    async def test_non_dict_body_noop(self) -> None:
        """Non-dict body → no-op."""
        op = GlomFlattenProcessor()
        ex = _exchange("string body")
        await op.process(ex, _ctx())
        assert ex.in_message.body == "string body"
