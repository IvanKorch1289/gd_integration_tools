"""Unit tests for :class:`AgentMemoryGateway` Protocol (Block 4.1, ADR-0075).

The interface defines a transport-agnostic gateway for AI-agent memory
(short-term Mongo + long-term PG/Qdrant) with mandatory tenant isolation.

Reference implementation: ``src/backend/core/interfaces/agent_memory.py``.

These tests cover the dataclasses (``MemoryMessage``/``MemoryFact``),
the Protocol contract (8 async methods), the ``@runtime_checkable``
behaviour, and a fake in-memory backend that exercises the round-trip
``save → recall → consolidate`` flow.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.interfaces.agent_memory import (
    AgentMemoryGateway,
    MemoryFact,
    MemoryMessage,
)

# ----------------------------------------------------------------------
# Fakes / helpers
# ----------------------------------------------------------------------


class _FakeAgentMemory:
    """In-memory implementation of :class:`AgentMemoryGateway` for tests.

    Satisfies the full Protocol surface (8 async methods) using plain
    dicts keyed by ``(tenant_id, session_id)``. Used to verify
    ``isinstance(..., AgentMemoryGateway)`` and to exercise the
    round-trip behaviour of the gateway contract.
    """

    def __init__(self) -> None:
        self.messages: dict[tuple[str, str], list[MemoryMessage]] = {}
        self.facts: dict[tuple[str, str], list[MemoryFact]] = {}
        self.scratchpads: dict[tuple[str, str], str] = {}
        self._next_id = 0
        self.call_log: list[tuple[str, ...]] = []

    def _id(self, prefix: str) -> str:
        self._next_id += 1
        return f"{prefix}_{self._next_id}"

    async def get_messages(
        self, *, tenant_id: str, session_id: str, limit: int = 50
    ) -> list[MemoryMessage]:
        self.call_log.append(("get_messages", tenant_id, session_id, str(limit)))
        msgs = self.messages.get((tenant_id, session_id), [])
        return msgs[-limit:]

    async def save_message(
        self,
        *,
        tenant_id: str,
        session_id: str,
        role: str,
        content: str,
        metadata: Any = None,
    ) -> str:
        self.call_log.append(("save_message", tenant_id, session_id, role))
        mid = self._id("m")
        msg = MemoryMessage(role=role, content=content, ts=0.0, metadata=metadata or {})
        self.messages.setdefault((tenant_id, session_id), []).append(msg)
        return mid

    async def get_facts(
        self, *, tenant_id: str, session_id: str | None = None, limit: int = 50
    ) -> list[MemoryFact]:
        self.call_log.append(("get_facts", tenant_id, str(session_id), str(limit)))
        out: list[MemoryFact] = []
        for (t, s), flist in self.facts.items():
            if t != tenant_id:
                continue
            if session_id is not None and s != session_id:
                continue
            out.extend(flist)
        return out[:limit]

    async def save_fact(
        self,
        *,
        tenant_id: str,
        content: str,
        confidence: float = 1.0,
        source_session_id: str | None = None,
        tags: tuple[str, ...] = (),
    ) -> str:
        self.call_log.append(("save_fact", tenant_id, content[:8]))
        fid = self._id("f")
        fact = MemoryFact(
            content=content,
            confidence=confidence,
            source_session_id=source_session_id,
            tags=tags,
        )
        self.facts.setdefault((tenant_id, source_session_id or "_"), []).append(fact)
        return fid

    async def recall_semantic(
        self, *, tenant_id: str, query: str, top_k: int = 5
    ) -> list[MemoryFact]:
        self.call_log.append(("recall_semantic", tenant_id, query, str(top_k)))
        out: list[MemoryFact] = []
        for (t, _), flist in self.facts.items():
            if t != tenant_id:
                continue
            for f in flist:
                if query in f.content:
                    out.append(f)
        return out[:top_k]

    async def get_scratchpad(self, *, tenant_id: str, session_id: str) -> str | None:
        return self.scratchpads.get((tenant_id, session_id))

    async def save_scratchpad(
        self, *, tenant_id: str, session_id: str, content: str
    ) -> None:
        self.scratchpads[(tenant_id, session_id)] = content

    async def consolidate(self, *, tenant_id: str, session_id: str) -> int:
        msgs = self.messages.get((tenant_id, session_id), [])
        added = 0
        for m in msgs:
            await self.save_fact(
                tenant_id=tenant_id,
                content=m.content,
                confidence=1.0,
                source_session_id=session_id,
                tags=("consolidated",),
            )
            added += 1
        return added


class _IncompleteAgentMemory:
    """Missing 6 of 8 methods — must fail ``isinstance`` Protocol check."""

    async def get_messages(
        self, *, tenant_id: str, session_id: str, limit: int = 50
    ) -> list[MemoryMessage]:
        del tenant_id, session_id, limit
        return []


# ----------------------------------------------------------------------
# DTO construction
# ----------------------------------------------------------------------


def test_memory_message_creation() -> None:
    """``MemoryMessage`` stores role/content/ts/metadata as a frozen dataclass."""
    msg = MemoryMessage(
        role="user", content="hello", ts=123.0, metadata={"model": "gpt"}
    )
    assert msg.role == "user"
    assert msg.content == "hello"
    assert msg.ts == 123.0
    assert msg.metadata == {"model": "gpt"}


def test_memory_message_is_frozen() -> None:
    """``MemoryMessage`` is ``frozen=True`` — mutation must raise ``FrozenInstanceError``."""
    msg = MemoryMessage(role="user", content="x", ts=0.0)
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        msg.content = "mutated"  # type: ignore[misc]


def test_memory_fact_creation() -> None:
    """``MemoryFact`` stores content/confidence/source/tags."""
    fact = MemoryFact(
        content="prefers Russian",
        confidence=0.9,
        source_session_id="sess-1",
        tags=("preference", "language"),
    )
    assert fact.content == "prefers Russian"
    assert fact.confidence == 0.9
    assert fact.source_session_id == "sess-1"
    assert fact.tags == ("preference", "language")


def test_memory_fact_defaults() -> None:
    """``MemoryFact`` has sensible defaults: source=None, tags=()."""
    fact = MemoryFact(content="x", confidence=0.5)
    assert fact.source_session_id is None
    assert fact.tags == ()


# ----------------------------------------------------------------------
# Protocol contract
# ----------------------------------------------------------------------


def test_protocol_is_runtime_checkable() -> None:
    """``AgentMemoryGateway`` Protocol is decorated ``@runtime_checkable``."""
    backend = _FakeAgentMemory()
    assert isinstance(backend, AgentMemoryGateway)


def test_protocol_rejects_incomplete_backend() -> None:
    """Backend with only 2 of 8 methods does not satisfy the Protocol."""
    incomplete = _IncompleteAgentMemory()
    assert not isinstance(incomplete, AgentMemoryGateway)


def test_protocol_declares_eight_methods() -> None:
    """The Protocol surface must include the 8 documented async methods."""
    expected = {
        "get_messages",
        "save_message",
        "get_facts",
        "save_fact",
        "recall_semantic",
        "get_scratchpad",
        "save_scratchpad",
        "consolidate",
    }
    for name in expected:
        assert hasattr(AgentMemoryGateway, name), f"Missing method: {name}"


# ----------------------------------------------------------------------
# Behavioural round-trip on fake backend
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_message_then_get_messages() -> None:
    """``save_message`` followed by ``get_messages`` returns the saved message."""
    backend = _FakeAgentMemory()
    mid = await backend.save_message(
        tenant_id="acme", session_id="s1", role="user", content="hello"
    )
    assert mid.startswith("m_")
    msgs = await backend.get_messages(tenant_id="acme", session_id="s1")
    assert len(msgs) == 1
    assert msgs[0].content == "hello"
    assert msgs[0].role == "user"


@pytest.mark.asyncio
async def test_recall_semantic_top_k_respected() -> None:
    """``recall_semantic`` caps results to ``top_k`` (lexical proxy)."""
    backend = _FakeAgentMemory()
    for i in range(7):
        await backend.save_fact(
            tenant_id="acme",
            content=f"cat fact {i}",
            confidence=0.8,
            source_session_id="s1",
        )
    found = await backend.recall_semantic(tenant_id="acme", query="cat", top_k=3)
    assert len(found) == 3
    assert all("cat" in f.content for f in found)


@pytest.mark.asyncio
async def test_metadata_propagation() -> None:
    """``metadata`` argument on ``save_message`` is preserved on the stored item."""
    backend = _FakeAgentMemory()
    meta = {"model": "gpt-4", "cost_usd": 0.002, "tenant_tag": "acme"}
    await backend.save_message(
        tenant_id="acme", session_id="s1", role="assistant", content="ok", metadata=meta
    )
    msgs = await backend.get_messages(tenant_id="acme", session_id="s1")
    assert msgs[0].metadata == meta


@pytest.mark.asyncio
async def test_scratchpad_roundtrip() -> None:
    """``save_scratchpad`` then ``get_scratchpad`` returns the same content."""
    backend = _FakeAgentMemory()
    assert await backend.get_scratchpad(tenant_id="acme", session_id="s1") is None
    await backend.save_scratchpad(
        tenant_id="acme", session_id="s1", content="TODO: add tests"
    )
    assert await backend.get_scratchpad(tenant_id="acme", session_id="s1") == (
        "TODO: add tests"
    )


@pytest.mark.asyncio
async def test_tenant_isolation() -> None:
    """Messages for one tenant must not leak into another's session view."""
    backend = _FakeAgentMemory()
    await backend.save_message(
        tenant_id="tenant_a", session_id="s1", role="user", content="secret-a"
    )
    await backend.save_message(
        tenant_id="tenant_b", session_id="s1", role="user", content="secret-b"
    )

    a_msgs = await backend.get_messages(tenant_id="tenant_a", session_id="s1")
    b_msgs = await backend.get_messages(tenant_id="tenant_b", session_id="s1")

    assert [m.content for m in a_msgs] == ["secret-a"]
    assert [m.content for m in b_msgs] == ["secret-b"]


@pytest.mark.asyncio
async def test_consolidate_moves_messages_to_facts() -> None:
    """``consolidate`` produces a fact per short-term message."""
    backend = _FakeAgentMemory()
    await backend.save_message(
        tenant_id="acme", session_id="s1", role="user", content="msg-1"
    )
    await backend.save_message(
        tenant_id="acme", session_id="s1", role="assistant", content="msg-2"
    )
    added = await backend.consolidate(tenant_id="acme", session_id="s1")
    assert added == 2
    facts = await backend.get_facts(tenant_id="acme", session_id="s1")
    assert {f.content for f in facts} == {"msg-1", "msg-2"}
    assert all("consolidated" in f.tags for f in facts)


# ----------------------------------------------------------------------
# Import & module surface
# ----------------------------------------------------------------------


def test_module_imports() -> None:
    """The module is importable from the ``core.interfaces`` package."""
    from src.backend.core.interfaces import agent_memory

    assert agent_memory is not None
    assert hasattr(agent_memory, "AgentMemoryGateway")
    assert hasattr(agent_memory, "MemoryFact")
    assert hasattr(agent_memory, "MemoryMessage")


def test_dunder_all_exports() -> None:
    """The module's ``__all__`` exposes the three public names exactly."""
    from src.backend.core.interfaces import agent_memory

    assert set(agent_memory.__all__) == {
        "AgentMemoryGateway",
        "MemoryFact",
        "MemoryMessage",
    }
