"""Unit test для Block 4.1 (gap-ai-4.1, ADR-0075).

Проверяет :class:`UnifiedMemoryGateway`:

1. tenant_id обязателен (ValueError при пустом).
2. get_messages/save_message → short_term.get_conversation/add_message.
3. get_facts(session_id=...) → short_term.get_facts; без session_id → long_term.recall.
4. recall_semantic → long_term.recall.
5. save_fact → long_term.add_semantic; fallback на short_term при long_term=None.
6. consolidate → long_term.consolidate; 0 при отсутствии long_term.
7. scratchpad → short_term.{get,set}_scratchpad.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.interfaces.agent_memory import MemoryMessage
from src.backend.services.ai.memory_gateway import UnifiedMemoryGateway


def _make_short_mock() -> AsyncMock:
    """Builder: AgentMemoryService stub с базовыми методами."""
    m = AsyncMock()
    m.get_conversation = AsyncMock(return_value=[])
    m.add_message = AsyncMock(return_value=None)
    m.get_facts = AsyncMock(return_value={})
    m.set_fact = AsyncMock(return_value=None)
    m.get_scratchpad = AsyncMock(return_value="")
    m.set_scratchpad = AsyncMock(return_value=None)
    return m


def _make_long_mock() -> AsyncMock:
    """Builder: LangMemService stub."""
    m = AsyncMock()
    m.recall = AsyncMock(return_value=[])
    m.add_semantic = AsyncMock(return_value="fact-id-123")
    m.consolidate = AsyncMock(return_value=5)
    return m


@pytest.mark.asyncio
async def test_tenant_id_required() -> None:
    """Все методы поднимают ValueError при пустом tenant_id."""
    gw = UnifiedMemoryGateway(
        short_term=_make_short_mock(), long_term=_make_long_mock()
    )
    with pytest.raises(ValueError, match="tenant_id обязателен"):
        await gw.get_messages(tenant_id="", session_id="s1")
    with pytest.raises(ValueError, match="tenant_id обязателен"):
        await gw.save_message(tenant_id="", session_id="s1", role="user", content="hi")
    with pytest.raises(ValueError, match="tenant_id обязателен"):
        await gw.get_scratchpad(tenant_id="", session_id="s1")


@pytest.mark.asyncio
async def test_get_messages_returns_typed() -> None:
    """get_messages → list[MemoryMessage] с tenant scoping."""
    short = _make_short_mock()
    short.get_conversation = AsyncMock(
        return_value=[
            {"role": "user", "content": "hi", "ts": 1.0, "metadata": {"x": 1}},
            {"role": "assistant", "content": "ok", "ts": 2.0},
        ]
    )
    gw = UnifiedMemoryGateway(short_term=short)
    messages = await gw.get_messages(tenant_id="t1", session_id="s1", limit=10)
    assert len(messages) == 2
    assert all(isinstance(m, MemoryMessage) for m in messages)
    short.get_conversation.assert_awaited_once_with("t1:s1", limit=10)


@pytest.mark.asyncio
async def test_save_message_passes_metadata() -> None:
    """save_message → short_term.add_message с tenant-scoped session_id."""
    short = _make_short_mock()
    gw = UnifiedMemoryGateway(short_term=short)
    msg_id = await gw.save_message(
        tenant_id="t1",
        session_id="s1",
        role="user",
        content="hello",
        metadata={"model": "gpt-4o-mini"},
    )
    short.add_message.assert_awaited_once()
    call = short.add_message.await_args
    assert call.args[0] == "t1:s1"
    assert call.kwargs["role"] == "user"
    assert call.kwargs["content"] == "hello"
    assert call.kwargs["metadata"]["model"] == "gpt-4o-mini"
    assert call.kwargs["metadata"]["id"] == msg_id


@pytest.mark.asyncio
async def test_get_facts_with_session_uses_short_term() -> None:
    """get_facts(session_id=...) → short_term.get_facts (key-value)."""
    short = _make_short_mock()
    short.get_facts = AsyncMock(return_value={"persona": "helpful", "lang": "ru"})
    long_ = _make_long_mock()
    gw = UnifiedMemoryGateway(short_term=short, long_term=long_)
    facts = await gw.get_facts(tenant_id="t1", session_id="s1")
    assert len(facts) == 2
    contents = {f.content for f in facts}
    assert "persona=helpful" in contents
    assert "lang=ru" in contents
    long_.recall.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_facts_without_session_uses_long_term() -> None:
    """get_facts(session_id=None) → long_term.recall."""
    short = _make_short_mock()
    long_ = _make_long_mock()
    long_.recall = AsyncMock(
        return_value=[
            {"content": "fact1", "confidence": 0.9},
            {"content": "fact2", "confidence": 0.7},
        ]
    )
    gw = UnifiedMemoryGateway(short_term=short, long_term=long_)
    facts = await gw.get_facts(tenant_id="t1")
    assert len(facts) == 2
    long_.recall.assert_awaited_once()


@pytest.mark.asyncio
async def test_recall_semantic_uses_long_term() -> None:
    """recall_semantic → long_term.recall(query, top_k)."""
    long_ = _make_long_mock()
    long_.recall = AsyncMock(return_value=[{"content": "found", "confidence": 0.95}])
    gw = UnifiedMemoryGateway(short_term=_make_short_mock(), long_term=long_)
    facts = await gw.recall_semantic(tenant_id="t1", query="кредит", top_k=3)
    assert len(facts) == 1
    assert facts[0].content == "found"
    long_.recall.assert_awaited_once_with(tenant_id="t1", query="кредит", top_k=3)


@pytest.mark.asyncio
async def test_recall_semantic_empty_when_long_term_none() -> None:
    """recall_semantic возвращает [] при long_term=None (graceful)."""
    gw = UnifiedMemoryGateway(short_term=_make_short_mock(), long_term=None)
    facts = await gw.recall_semantic(tenant_id="t1", query="x")
    assert facts == []


@pytest.mark.asyncio
async def test_save_fact_uses_long_term() -> None:
    """save_fact → long_term.add_semantic."""
    long_ = _make_long_mock()
    gw = UnifiedMemoryGateway(short_term=_make_short_mock(), long_term=long_)
    fact_id = await gw.save_fact(
        tenant_id="t1", content="x", confidence=0.8, tags=("preference",)
    )
    assert fact_id == "fact-id-123"
    long_.add_semantic.assert_awaited_once()


@pytest.mark.asyncio
async def test_save_fact_fallback_to_short_term() -> None:
    """save_fact → short_term.set_fact при long_term=None."""
    short = _make_short_mock()
    gw = UnifiedMemoryGateway(short_term=short, long_term=None)
    fact_id = await gw.save_fact(tenant_id="t1", content="x")
    assert fact_id.startswith("fact_")
    short.set_fact.assert_awaited_once()


@pytest.mark.asyncio
async def test_consolidate_uses_long_term() -> None:
    """consolidate → long_term.consolidate с tenant-scoped session_id."""
    long_ = _make_long_mock()
    gw = UnifiedMemoryGateway(short_term=_make_short_mock(), long_term=long_)
    count = await gw.consolidate(tenant_id="t1", session_id="s1")
    assert count == 5
    long_.consolidate.assert_awaited_once_with(session_id="t1:s1")


@pytest.mark.asyncio
async def test_consolidate_returns_zero_without_long_term() -> None:
    """consolidate возвращает 0 при long_term=None."""
    gw = UnifiedMemoryGateway(short_term=_make_short_mock(), long_term=None)
    count = await gw.consolidate(tenant_id="t1", session_id="s1")
    assert count == 0


@pytest.mark.asyncio
async def test_scratchpad_round_trip() -> None:
    """get_scratchpad / save_scratchpad → short_term.{get,set}_scratchpad."""
    short = _make_short_mock()
    short.get_scratchpad = AsyncMock(return_value="my notes")
    gw = UnifiedMemoryGateway(short_term=short)
    await gw.save_scratchpad(tenant_id="t1", session_id="s1", content="updated")
    short.set_scratchpad.assert_awaited_once_with("t1:s1", "updated")
    value = await gw.get_scratchpad(tenant_id="t1", session_id="s1")
    assert value == "my notes"


@pytest.mark.asyncio
async def test_protocol_runtime_check() -> None:
    """UnifiedMemoryGateway удовлетворяет AgentMemoryGateway Protocol."""
    from src.backend.core.interfaces.agent_memory import AgentMemoryGateway

    gw = UnifiedMemoryGateway(short_term=_make_short_mock())
    assert isinstance(gw, AgentMemoryGateway)


@pytest.mark.asyncio
async def test_graceful_on_backend_failure() -> None:
    """get_messages → [] при exception в short_term (graceful)."""
    short = _make_short_mock()
    short.get_conversation = AsyncMock(side_effect=RuntimeError("backend down"))
    gw = UnifiedMemoryGateway(short_term=short)
    messages = await gw.get_messages(tenant_id="t1", session_id="s1")
    assert messages == []
