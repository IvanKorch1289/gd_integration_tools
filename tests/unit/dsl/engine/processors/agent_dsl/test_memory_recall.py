"""Unit-тесты для :class:`MemoryRecallProcessor` (S27 W3)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.memory_recall import (
    MemoryRecallProcessor,
)


class _Fact:
    def __init__(self, content: str, confidence: float = 1.0) -> None:
        self.content = content
        self.confidence = confidence


class _FakeMemoryBackend:
    def __init__(self, records: list[dict[str, Any]] | None = None) -> None:
        self.records = records or []
        self.calls: list[dict[str, Any]] = []

    async def recall_semantic(
        self,
        *,
        tenant_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[Any]:
        self.calls.append({"tenant_id": tenant_id, "query": query, "top_k": top_k})
        return [
            _Fact(content=str(r.get("value", r)), confidence=1.0)
            for r in self.records[:top_k]
        ]


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_namespace() -> None:
    with pytest.raises(ValueError, match="namespace обязателен"):
        MemoryRecallProcessor(namespace="", query="q")


def test_init_validates_query_or_property() -> None:
    with pytest.raises(ValueError, match="query или query_property"):
        MemoryRecallProcessor(namespace="ns")


def test_init_validates_k_positive() -> None:
    with pytest.raises(ValueError, match="k должен быть >=1"):
        MemoryRecallProcessor(namespace="ns", query="q", k=0)


def test_capability_scope_extracts_after_colon() -> None:
    proc = MemoryRecallProcessor(namespace="acme:credit_chat", query="q")
    assert proc._capability_scope(Exchange()) == "credit_chat"


def test_capability_scope_no_colon() -> None:
    proc = MemoryRecallProcessor(namespace="just_a_name", query="q")
    assert proc._capability_scope(Exchange()) == "just_a_name"


@pytest.mark.asyncio
async def test_happy_path_writes_records(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend(
        records=[{"key": "k1", "value": "v1"}, {"key": "k2", "value": "v2"}]
    )
    monkeypatch.setattr(
        MemoryRecallProcessor, "_resolve_backend", staticmethod(lambda: backend)
    )

    ex: Exchange[Any] = Exchange()
    proc = MemoryRecallProcessor(namespace="acme:chat", query="user question", k=2)
    await proc.process(ex, context)

    result = ex.get_property("memory_recall")
    assert len(result) == 2
    assert backend.calls[0] == {
        "tenant_id": "acme:chat",
        "query": "user question",
        "top_k": 2,
    }


@pytest.mark.asyncio
async def test_dynamic_query_from_body(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryRecallProcessor, "_resolve_backend", staticmethod(lambda: backend)
    )

    ex: Exchange[Any] = Exchange(
        in_message=Message(body={"user_input": "dynamic query here"})
    )
    proc = MemoryRecallProcessor(
        namespace="acme:chat", query_property="body.user_input"
    )
    await proc.process(ex, context)

    assert backend.calls[0]["query"] == "dynamic query here"


@pytest.mark.asyncio
async def test_tenant_id_placeholder(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    backend = _FakeMemoryBackend()
    monkeypatch.setattr(
        MemoryRecallProcessor, "_resolve_backend", staticmethod(lambda: backend)
    )

    ex: Exchange[Any] = Exchange()
    ex.meta.tenant_id = "acme_corp"
    proc = MemoryRecallProcessor(namespace="${tenant_id}:credit_chat", query="q")
    await proc.process(ex, context)

    assert backend.calls[0]["tenant_id"] == "acme_corp:credit_chat"


@pytest.mark.asyncio
async def test_backend_unavailable_writes_empty_list(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        MemoryRecallProcessor, "_resolve_backend", staticmethod(lambda: None)
    )

    ex: Exchange[Any] = Exchange()
    proc = MemoryRecallProcessor(namespace="ns", query="q")
    await proc.process(ex, context)

    assert ex.get_property("memory_recall") == []


@pytest.mark.asyncio
async def test_backend_exception_writes_empty(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """Если backend.recall() raises — empty result + no error в exchange."""
    from src.backend.core.config.features import feature_flags

    class _BrokenBackend:
        async def recall(self, *args: Any, **kwargs: Any) -> Any:
            del args, kwargs
            raise RuntimeError("backend kaboom")

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        MemoryRecallProcessor,
        "_resolve_backend",
        staticmethod(lambda: _BrokenBackend()),
    )

    ex: Exchange[Any] = Exchange()
    proc = MemoryRecallProcessor(namespace="ns", query="q")
    await proc.process(ex, context)

    assert ex.get_property("memory_recall") == []
    assert ex.error is None


def test_to_spec_round_trip() -> None:
    proc = MemoryRecallProcessor(
        namespace="acme:credit_chat",
        query_property="body.user_input",
        k=10,
        result_property="ctx",
    )
    spec = proc.to_spec()
    assert spec == {
        "memory_recall": {
            "namespace": "acme:credit_chat",
            "k": 10,
            "query_property": "body.user_input",
            "result_property": "ctx",
        }
    }
