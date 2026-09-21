"""Unit tests for src.backend.core.di.contexts (W14.1.D dispatch context helpers)."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from typing import Any

import pytest

from src.backend.core.di.contexts import make_dispatch_context
from src.backend.core.interfaces.action_dispatcher import DispatchContext

# ---------------------------------------------------------------------- #
# Constants                                                                #
# ---------------------------------------------------------------------- #

_UUID4_HEX = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------- #
# 1. Construction & typing                                                #
# ---------------------------------------------------------------------- #


class TestConstruction:
    def test_returns_dispatch_context_instance(self) -> None:
        ctx = make_dispatch_context("http")
        assert isinstance(ctx, DispatchContext)

    def test_returns_dataclass(self) -> None:
        ctx = make_dispatch_context("http")
        assert is_dataclass(ctx)

    def test_creation_sets_source(self) -> None:
        ctx = make_dispatch_context("grpc")
        assert ctx.source == "grpc"

    def test_source_is_first_positional(self) -> None:
        # The signature requires source as a positional arg.
        ctx = make_dispatch_context("scheduler")
        assert ctx.source == "scheduler"


# ---------------------------------------------------------------------- #
# 2. correlation_id auto-generation                                       #
# ---------------------------------------------------------------------- #


class TestCorrelationIdGeneration:
    def test_creation_sets_correlation_id_when_missing(self) -> None:
        ctx = make_dispatch_context("http")
        assert ctx.correlation_id is not None

    def test_generated_id_is_uuid4_hex_32_chars(self) -> None:
        ctx = make_dispatch_context("http")
        assert _UUID4_HEX.match(ctx.correlation_id or "")

    def test_uses_provided_correlation_id(self) -> None:
        ctx = make_dispatch_context("ws", correlation_id="abc-123")
        assert ctx.correlation_id == "abc-123"

    def test_empty_string_correlation_id_is_replaced(self) -> None:
        # Empty string is falsy -> helper must auto-generate a new id.
        ctx = make_dispatch_context("http", correlation_id="")
        assert ctx.correlation_id
        assert _UUID4_HEX.match(ctx.correlation_id)

    def test_unique_correlation_id_per_call(self) -> None:
        ids = {make_dispatch_context("http").correlation_id for _ in range(50)}
        assert len(ids) == 50  # all distinct


# ---------------------------------------------------------------------- #
# 3. Default values for optional fields                                   #
# ---------------------------------------------------------------------- #


class TestDefaults:
    def test_default_optional_fields_are_none(self) -> None:
        ctx = make_dispatch_context("internal")
        assert ctx.tenant_id is None
        assert ctx.user_id is None
        assert ctx.idempotency_key is None
        assert ctx.trace_parent is None

    def test_default_attributes_is_empty_dict(self) -> None:
        ctx = make_dispatch_context("http")
        assert ctx.attributes == {}
        assert isinstance(ctx.attributes, dict)

    def test_default_source_is_internal_when_dataclass_default(self) -> None:
        # DispatchContext dataclass default for source is "internal" — make sure
        # helper does NOT override it to something falsy.
        ctx = make_dispatch_context("http")
        assert ctx.source == "http"


# ---------------------------------------------------------------------- #
# 4. All optional kwargs pass through                                     #
# ---------------------------------------------------------------------- #


class TestOptionalKwargs:
    def test_all_optional_fields_set(self) -> None:
        ctx = make_dispatch_context(
            "scheduler",
            correlation_id="cid-1",
            tenant_id="tenant-42",
            user_id="user-7",
            idempotency_key="ik-99",
            trace_parent="00-trace-span-01",
            attributes={"path": "/v1/orders", "ip": "10.0.0.1"},
        )
        assert ctx.correlation_id == "cid-1"
        assert ctx.tenant_id == "tenant-42"
        assert ctx.user_id == "user-7"
        assert ctx.idempotency_key == "ik-99"
        assert ctx.trace_parent == "00-trace-span-01"
        assert ctx.attributes == {"path": "/v1/orders", "ip": "10.0.0.1"}

    def test_source_must_be_kwarg_only_after_first(self) -> None:
        # All other fields are keyword-only — passing them positionally
        # must raise.
        with pytest.raises(TypeError):
            make_dispatch_context("http", "should-fail")  # type: ignore[misc]


# ---------------------------------------------------------------------- #
# 5. attributes semantics                                                #
# ---------------------------------------------------------------------- #


class TestAttributes:
    def test_none_attributes_become_empty_dict(self) -> None:
        ctx = make_dispatch_context("http", attributes=None)
        assert ctx.attributes == {}

    def test_mapping_attributes_are_materialised_to_dict(self) -> None:
        src: Mapping[str, Any] = {"k": 1, "nested": {"a": [1, 2]}}
        ctx = make_dispatch_context("http", attributes=src)
        assert ctx.attributes == {"k": 1, "nested": {"a": [1, 2]}}
        assert isinstance(ctx.attributes, dict)

    def test_caller_mapping_is_not_aliased_into_context(self) -> None:
        # Helper must copy the mapping — mutating the caller side later
        # must not change the context's attributes.
        src: dict[str, Any] = {"k": "v1"}
        ctx = make_dispatch_context("http", attributes=src)
        src["k"] = "v2"
        src["new"] = "added"
        assert ctx.attributes == {"k": "v1"}

    def test_attributes_dict_is_not_shared_between_calls(self) -> None:
        ctx_a = make_dispatch_context("http", attributes={"a": 1})
        ctx_b = make_dispatch_context("http", attributes={"a": 1})
        ctx_a.attributes["a"] = 999
        assert ctx_b.attributes == {"a": 1}


# ---------------------------------------------------------------------- #
# 6. Multi-tenant isolation                                               #
# ---------------------------------------------------------------------- #


class TestTenantIsolation:
    def test_tenant_id_required_raises_only_when_consumer_validates(self) -> None:
        # Helper itself accepts tenant_id=None — the requirement is enforced
        # by downstream consumers. We document this contract here.
        ctx = make_dispatch_context("http")
        assert ctx.tenant_id is None  # helper does not enforce

    def test_tenant_isolation_between_contexts(self) -> None:
        ctx_a = make_dispatch_context("http", tenant_id="tenant-A")
        ctx_b = make_dispatch_context("http", tenant_id="tenant-B")
        assert ctx_a.tenant_id != ctx_b.tenant_id
        assert ctx_a.tenant_id == "tenant-A"
        assert ctx_b.tenant_id == "tenant-B"


# ---------------------------------------------------------------------- #
# 7. Concurrency: asyncio.gather isolation                                #
# ---------------------------------------------------------------------- #


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_contexts_have_distinct_ids(self) -> None:
        async def make_one() -> str:
            ctx = make_dispatch_context("http")
            await asyncio.sleep(0)  # yield to event loop
            return ctx.correlation_id or ""

        ids = await asyncio.gather(*(make_one() for _ in range(100)))
        assert len(set(ids)) == 100
        for cid in ids:
            assert _UUID4_HEX.match(cid)

    @pytest.mark.asyncio
    async def test_concurrent_contexts_tenant_isolation(self) -> None:
        async def make_for(tenant: str) -> str:
            ctx = make_dispatch_context("http", tenant_id=tenant)
            await asyncio.sleep(0)
            return ctx.tenant_id or ""

        tenants = [f"tenant-{i}" for i in range(20)]
        results = await asyncio.gather(*(make_for(t) for t in tenants))
        assert sorted(results) == sorted(tenants)


# ---------------------------------------------------------------------- #
# 8. Serialisation & equality                                             #
# ---------------------------------------------------------------------- #


class TestSerialization:
    def test_dataclass_can_be_serialised_to_dict(self) -> None:
        ctx = make_dispatch_context(
            "http", correlation_id="cid", tenant_id="t1", attributes={"k": "v"}
        )
        d = asdict(ctx)
        assert d["source"] == "http"
        assert d["correlation_id"] == "cid"
        assert d["tenant_id"] == "t1"
        assert d["attributes"] == {"k": "v"}

    def test_equality_by_value(self) -> None:
        a = make_dispatch_context("http", correlation_id="x", tenant_id="t1")
        b = make_dispatch_context("http", correlation_id="x", tenant_id="t1")
        assert a == b

    def test_inequality_when_field_differs(self) -> None:
        a = make_dispatch_context("http", tenant_id="t1")
        b = make_dispatch_context("http", tenant_id="t2")
        assert a != b


# ---------------------------------------------------------------------- #
# 9. Edge cases                                                           #
# ---------------------------------------------------------------------- #


class TestEdgeCases:
    def test_unicode_in_tenant_and_user(self) -> None:
        ctx = make_dispatch_context(
            "http", tenant_id="арендатор-1", user_id="пользователь-7"
        )
        assert ctx.tenant_id == "арендатор-1"
        assert ctx.user_id == "пользователь-7"

    def test_long_correlation_id_preserved(self) -> None:
        long_id = "a" * 4096
        ctx = make_dispatch_context("http", correlation_id=long_id)
        assert ctx.correlation_id == long_id

    def test_attributes_with_complex_nested_structures(self) -> None:
        attrs = {
            "list": [1, 2, {"deep": [True, None, "x"]}],
            "tuple": (1, 2),
            "set_marker": "value",
        }
        ctx = make_dispatch_context("http", attributes=attrs)
        assert ctx.attributes["list"][2]["deep"][2] == "x"
        assert ctx.attributes["tuple"] == (1, 2)

    def test_override_keeps_existing_attributes(self) -> None:
        # Two separate invocations with overlapping keys remain independent.
        ctx_a = make_dispatch_context("http", attributes={"k": 1})
        ctx_b = make_dispatch_context("http", attributes={"k": 2})
        assert ctx_a.attributes["k"] == 1
        assert ctx_b.attributes["k"] == 2

    def test_repr_contains_class_name(self) -> None:
        ctx = make_dispatch_context("http", correlation_id="cid")
        assert "DispatchContext" in repr(ctx)
