"""Unit-тесты для :class:`MemoryStoreProcessor` (S27 W3)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.memory_store import (
    MemoryStoreProcessor,
)


class _FakeMemoryBackend:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def save_fact(
        self,
        *,
        tenant_id: str,
        content: str,
        tags: tuple[str, ...] = (),
    ) -> None:
        self.calls.append(
            {"tenant_id": tenant_id, "content": content, "tags": tags},
        )


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_namespace() -> None:
    with pytest.raises(ValueError, match="namespace обязателен"):
        MemoryStoreProcessor(namespace="", key="k")


def test_init_validates_key_or_property() -> None:
    with pytest.raises(ValueError, match="key или key_property"):
        MemoryStoreProcessor(namespace="ns")


def test_capability_scope_extracts_after_colon() -> None:
    proc = MemoryStoreProcessor(namespace="acme:chat", key="k1")
    assert proc._capability_scope(Exchange()) == "chat"


@pytest.mark.asyncio
async def test_happy_path_static_key(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryStoreProcessor, "_resolve_backend", staticmethod(lambda: backend),
    )

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", {"content": "stored value"})
    proc = MemoryStoreProcessor(namespace="acme:chat", key="static_key", ttl_s=3600)
    await proc.process(ex, context)

    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["tenant_id"] == "acme:chat"
    assert call["content"] == "{'content': 'stored value'}"
    # user_key tag = static_key
    assert call["tags"] == ("user_key", "static_key")


@pytest.mark.asyncio
async def test_dynamic_key_from_meta(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryStoreProcessor, "_resolve_backend", staticmethod(lambda: backend),
    )

    ex: Exchange[Any] = Exchange()
    ex.meta.correlation_id = "req-xyz-123"
    ex.set_property("agent_result", {"content": "v"})
    proc = MemoryStoreProcessor(
        namespace="acme:chat", key_property="meta.correlation_id",
    )
    await proc.process(ex, context)

    assert backend.calls[0]["tags"][1] == "req-xyz-123"


@pytest.mark.asyncio
async def test_dynamic_key_from_body(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryStoreProcessor, "_resolve_backend", staticmethod(lambda: backend),
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body={"user_id": "user_42"}))
    ex.set_property("agent_result", {"content": "v"})
    proc = MemoryStoreProcessor(namespace="acme:chat", key_property="body.user_id")
    await proc.process(ex, context)

    assert backend.calls[0]["tags"][1] == "user_42"


@pytest.mark.asyncio
async def test_custom_value_property(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryStoreProcessor, "_resolve_backend", staticmethod(lambda: backend),
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body={"foo": "bar"}))
    proc = MemoryStoreProcessor(namespace="ns", key="k", value_property="body.foo")
    await proc.process(ex, context)

    assert backend.calls[0]["content"] == "bar"


@pytest.mark.asyncio
async def test_tenant_id_placeholder(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryStoreProcessor, "_resolve_backend", staticmethod(lambda: backend),
    )

    ex: Exchange[Any] = Exchange()
    ex.meta.tenant_id = "tenantX"
    ex.set_property("agent_result", "v")
    proc = MemoryStoreProcessor(namespace="${tenant_id}:chat", key="k")
    await proc.process(ex, context)

    assert backend.calls[0]["tenant_id"] == "tenantX:chat"


@pytest.mark.asyncio
async def test_value_missing_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext,
) -> None:
    """Когда value=None — store не вызывается."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryStoreProcessor, "_resolve_backend", staticmethod(lambda: backend),
    )

    ex: Exchange[Any] = Exchange()
    # agent_result не выставлен — value будет None
    proc = MemoryStoreProcessor(namespace="ns", key="k")
    await proc.process(ex, context)

    assert backend.calls == []


@pytest.mark.asyncio
async def test_backend_unavailable_no_error(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext,
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        MemoryStoreProcessor, "_resolve_backend", staticmethod(lambda: None),
    )

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", "v")
    proc = MemoryStoreProcessor(namespace="ns", key="k")
    await proc.process(ex, context)

    assert ex.error is None


def test_to_spec_round_trip() -> None:
    proc = MemoryStoreProcessor(
        namespace="acme:chat",
        key_property="meta.exchange_id",
        value_property="body.summary",
        ttl_s=86400,
    )
    spec = proc.to_spec()
    assert spec == {
        "memory_store": {
            "namespace": "acme:chat",
            "key_property": "meta.exchange_id",
            "value_property": "body.summary",
            "ttl_s": 86400,
        },
    }
