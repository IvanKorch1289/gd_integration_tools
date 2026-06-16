"""Regression tests для LangGraph Checkpointer integration (S100 W1).

Покрывает:
* ``_langgraph_checkpoint_get_activity`` — None при недоступности saver,
  state при успехе, exception-isolation.
* ``_langgraph_checkpoint_put_activity`` — False при no thread_id /
  недоступном saver, True при успехе.
* ``register_langgraph_checkpoint_activities`` — корректно регистрирует
  обе activity в ``ActivityBridge._cache``.
* ``compile_agent_invoke_step`` — durable=True использует checkpoint,
  durable=False — пропускает; thread_id generation; sandbox-safe (no
  direct I/O in workflow code).

Pattern: activity-level тесты mock'ают ``get_langgraph_postgres_saver``
на source module (lazy import). Workflow-level тесты mock'ают
``temporalio.workflow.execute_activity`` через ``sys.modules`` injection
(как в ``test_step_compilers.py``).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.workflow.compiler.activity_bridge import (
    LANGGRAPH_CHECKPOINT_GET_ACTIVITY,
    LANGGRAPH_CHECKPOINT_PUT_ACTIVITY,
    ActivityBridge,
    _langgraph_checkpoint_get_activity,
    _langgraph_checkpoint_put_activity,
    register_langgraph_checkpoint_activities,
)

# NOTE: ``AgentInvokeDeclaration`` is NOT imported at module-level because
# Pydantic forward reference (MemoryScope) требует чтобы spec/__init__.py
# полностью отработал ДО инстанцирования. Импорт внутри функции
# (как в test_step_compilers.py:380) — канонический паттерн.


# --- Activity-level tests ----------------------------------------------------


@pytest.mark.asyncio
async def test_checkpoint_get_returns_none_when_saver_unavailable() -> None:
    """Saver unavailable (flag OFF / no langchain_postgres) → None.

    Caller обрабатывает None как "первый запуск, нет prior state".
    """
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(return_value=None),
    ):
        result = await _langgraph_checkpoint_get_activity("agent-1:corr-1")
    assert result is None


@pytest.mark.asyncio
async def test_checkpoint_get_returns_state_when_available() -> None:
    """Saver available, aget returns state → dict returned."""
    fake_saver = MagicMock()
    fake_saver.aget = AsyncMock(
        return_value={"v": 1, "id": "chk-abc", "values": {"prompt": "hi"}}
    )
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(return_value=fake_saver),
    ):
        result = await _langgraph_checkpoint_get_activity("agent-1:corr-1")
    assert isinstance(result, dict)
    assert result.get("id") == "chk-abc"
    fake_saver.aget.assert_awaited_once_with(
        {"configurable": {"thread_id": "agent-1:corr-1"}}
    )


@pytest.mark.asyncio
async def test_checkpoint_get_aget_returns_none_yields_none() -> None:
    """Saver OK, but aget returns None (no prior checkpoint) → None."""
    fake_saver = MagicMock()
    fake_saver.aget = AsyncMock(return_value=None)
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(return_value=fake_saver),
    ):
        result = await _langgraph_checkpoint_get_activity("thread-x")
    assert result is None


@pytest.mark.asyncio
async def test_checkpoint_get_isolates_saver_exceptions() -> None:
    """saver.aget raises → returns None (does NOT propagate)."""
    fake_saver = MagicMock()
    fake_saver.aget = AsyncMock(side_effect=RuntimeError("db down"))
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(return_value=fake_saver),
    ):
        result = await _langgraph_checkpoint_get_activity("thread-x")
    assert result is None


@pytest.mark.asyncio
async def test_checkpoint_put_returns_false_without_thread_id() -> None:
    """state без thread_id → False, NO saver call."""
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(),
    ) as mock_saver:
        result = await _langgraph_checkpoint_put_activity(
            {"agent_id": "x", "output_summary": "y"}  # no thread_id
        )
    assert result is False
    mock_saver.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkpoint_put_returns_false_when_saver_unavailable() -> None:
    """Saver None → False (NOT raise)."""
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(return_value=None),
    ):
        result = await _langgraph_checkpoint_put_activity(
            {"thread_id": "t1", "agent_id": "x"}
        )
    assert result is False


@pytest.mark.asyncio
async def test_checkpoint_put_persists_state_with_saver() -> None:
    """Saver OK → aput called with (config, state, {}), returns True."""
    fake_saver = MagicMock()
    fake_saver.aput = AsyncMock(return_value={"configurable": {"thread_id": "t1"}})
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(return_value=fake_saver),
    ):
        result = await _langgraph_checkpoint_put_activity(
            {"thread_id": "t1", "agent_id": "agent-x", "output_summary": "ok"}
        )
    assert result is True
    fake_saver.aput.assert_awaited_once()
    args = fake_saver.aput.await_args.args
    assert args[0] == {"configurable": {"thread_id": "t1"}}
    assert args[1]["thread_id"] == "t1"
    assert args[1]["agent_id"] == "agent-x"
    assert args[2] == {}


@pytest.mark.asyncio
async def test_checkpoint_put_isolates_saver_exceptions() -> None:
    """saver.aput raises → returns False (does NOT propagate)."""
    fake_saver = MagicMock()
    fake_saver.aput = AsyncMock(side_effect=RuntimeError("write failed"))
    with patch(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        new=AsyncMock(return_value=fake_saver),
    ):
        result = await _langgraph_checkpoint_put_activity(
            {"thread_id": "t1", "agent_id": "x"}
        )
    assert result is False


# --- Bridge registration test -----------------------------------------------


def test_register_langgraph_checkpoint_activities_populates_cache() -> None:
    """register_langgraph_checkpoint_activities adds 2 entries в cache."""
    bridge = ActivityBridge()
    assert LANGGRAPH_CHECKPOINT_GET_ACTIVITY not in bridge._cache
    assert LANGGRAPH_CHECKPOINT_PUT_ACTIVITY not in bridge._cache

    register_langgraph_checkpoint_activities(bridge)

    assert LANGGRAPH_CHECKPOINT_GET_ACTIVITY in bridge._cache
    assert LANGGRAPH_CHECKPOINT_PUT_ACTIVITY in bridge._cache
    # Each cached entry is the activity function (idempotent re-registration)
    assert (
        bridge._cache[LANGGRAPH_CHECKPOINT_GET_ACTIVITY]
        is _langgraph_checkpoint_get_activity
    )
    assert (
        bridge._cache[LANGGRAPH_CHECKPOINT_PUT_ACTIVITY]
        is _langgraph_checkpoint_put_activity
    )


def test_register_is_idempotent() -> None:
    """Повторный register не плодит дубликаты в cache."""
    bridge = ActivityBridge()
    register_langgraph_checkpoint_activities(bridge)
    n = len(bridge._cache)
    register_langgraph_checkpoint_activities(bridge)
    assert len(bridge._cache) == n


# --- Workflow-level test (compile_agent_invoke_step durable mode) ------------


def _make_fake_temporal(
    *, execute_activity_handler: Any = None
) -> tuple[SimpleNamespace, list[dict[str, Any]]]:
    """Build fake ``temporalio.workflow`` module with recorded execute_activity.

    Args:
        execute_activity_handler: optional callable ``(name, *args, **kwargs)``
            invoked for each ``execute_activity`` call. If None, default returns
            ``None`` (caller can introspect ``recorder``).
    """
    recorder: list[dict[str, Any]] = []

    async def fake_execute_activity(name: str, *args: Any, **kwargs: Any) -> Any:
        call: dict[str, Any] = {"name": name, "args": args, "kwargs": kwargs}
        recorder.append(call)
        if execute_activity_handler is not None:
            return await execute_activity_handler(name, *args, **kwargs)
        return None

    return SimpleNamespace(execute_activity=fake_execute_activity), recorder


def _make_declaration(durable: bool):  # type: ignore[no-untyped-def]
    # Pydantic forward reference (MemoryScope) требует чтобы все forward
    # refs были в globals ПЕРЕД model_rebuild. Импортируем ВСЕ spec
    # submodules чтобы MemoryScope был в globals, потом rebuild.
    from src.backend.dsl.workflow.spec import AgentInvokeDeclaration  # noqa: F401
    from src.backend.dsl.workflow.spec.advanced_declarations import (
        AgentInvokeDeclaration as _AdvAID,
    )
    from src.backend.dsl.workflow.spec.policies import MemoryScope  # noqa: F401

    # Rebuild in the module's own globals so MemoryScope resolves.
    _AdvAID.model_rebuild()
    return AgentInvokeDeclaration(
        agent_id="agent-test", durable=durable, max_turns=3, timeout_s=60.0
    )


@pytest.mark.asyncio
async def test_compile_agent_invoke_durable_calls_checkpoint_get_and_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """durable=True → checkpoint_get + _agent_invoke + checkpoint_put.

    Sandbox-safe: никаких прямых I/O вызовов в workflow коде —
    все DB операции через workflow.execute_activity.
    """
    from src.backend.dsl.workflow.compiler import step_compilers

    decl = _make_declaration(durable=True)
    ctx: dict[str, Any] = {
        "_input": {"q": "hello"},
        "_tenant_id": "tenant-x",
        "_correlation_id": "corr-42",
    }

    fake_prior: dict[str, Any] = {"id": "prev-1", "values": {"prompt": "hi"}}
    fake_result: dict[str, Any] = {"content": "answer", "model_used": "gpt-4"}

    async def handler(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == LANGGRAPH_CHECKPOINT_GET_ACTIVITY:
            assert args[0] == "agent-test:corr-42"  # thread_id
            return fake_prior
        if name == "_agent_invoke":
            return fake_result
        if name == LANGGRAPH_CHECKPOINT_PUT_ACTIVITY:
            state = args[0]
            assert state["thread_id"] == "agent-test:corr-42"
            assert state["agent_id"] == "agent-test"
            assert state["tenant_id"] == "tenant-x"
            assert state["prior_summary"] == str(fake_prior)[:500]
            assert state["output_summary"] == str(fake_result)[:1000]
            return True
        raise AssertionError(f"Unexpected activity: {name}")

    fake_wf, recorder = _make_fake_temporal(execute_activity_handler=handler)
    monkeypatch.setitem(sys.modules, "temporalio", SimpleNamespace(workflow=fake_wf))
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)

    result = await step_compilers.compile_agent_invoke_step(decl, ctx)

    assert result == fake_result
    assert ctx.get("_outputs") is None  # no output_key in decl
    activity_names = [c["name"] for c in recorder]
    assert activity_names == [
        LANGGRAPH_CHECKPOINT_GET_ACTIVITY,
        "_agent_invoke",
        LANGGRAPH_CHECKPOINT_PUT_ACTIVITY,
    ]


@pytest.mark.asyncio
async def test_compile_agent_invoke_non_durable_skips_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """durable=False → only _agent_invoke call, NO checkpoint get/put."""
    from src.backend.dsl.workflow.compiler import step_compilers

    decl = _make_declaration(durable=False)
    ctx: dict[str, Any] = {"_input": {"q": "hello"}, "_correlation_id": "corr-99"}

    async def handler(name: str, *args: Any, **kwargs: Any) -> Any:
        return {"content": "ok"}

    fake_wf, recorder = _make_fake_temporal(execute_activity_handler=handler)
    monkeypatch.setitem(sys.modules, "temporalio", SimpleNamespace(workflow=fake_wf))
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)

    result = await step_compilers.compile_agent_invoke_step(decl, ctx)

    activity_names = [c["name"] for c in recorder]
    assert activity_names == ["_agent_invoke"]
    assert result == {"content": "ok"}


@pytest.mark.asyncio
async def test_compile_agent_invoke_durable_thread_id_from_correlation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """thread_id format: ``{agent_id}:{correlation_id}``."""
    from src.backend.dsl.workflow.compiler import step_compilers

    decl = _make_declaration(durable=True)
    ctx: dict[str, Any] = {"_input": {}, "_correlation_id": "corr-xyz"}

    captured_thread_ids: list[str] = []

    async def handler(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == LANGGRAPH_CHECKPOINT_GET_ACTIVITY:
            captured_thread_ids.append(args[0])
            return None
        if name == "_agent_invoke":
            return {"content": "ok"}
        if name == LANGGRAPH_CHECKPOINT_PUT_ACTIVITY:
            captured_thread_ids.append(args[0]["thread_id"])
            return True
        raise AssertionError(f"Unexpected: {name}")

    fake_wf, _ = _make_fake_temporal(execute_activity_handler=handler)
    monkeypatch.setitem(sys.modules, "temporalio", SimpleNamespace(workflow=fake_wf))
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)

    await step_compilers.compile_agent_invoke_step(decl, ctx)

    assert captured_thread_ids == ["agent-test:corr-xyz", "agent-test:corr-xyz"]


@pytest.mark.asyncio
async def test_compile_agent_invoke_durable_degrades_when_saver_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """durable=True, but checkpoint_get returns None → still works.

    This is the "durable degrades to stateless" path — flag OFF или
    langchain_postgres не установлен. Workflow НЕ падает, agent
    invocation still completes.
    """
    from src.backend.dsl.workflow.compiler import step_compilers

    decl = _make_declaration(durable=True)
    ctx: dict[str, Any] = {"_input": {"q": "hi"}, "_correlation_id": "corr-degraded"}

    async def handler(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == LANGGRAPH_CHECKPOINT_GET_ACTIVITY:
            return None  # saver unavailable
        if name == "_agent_invoke":
            return {"content": "degraded result"}
        if name == LANGGRAPH_CHECKPOINT_PUT_ACTIVITY:
            # prior_summary should be None (no prior state loaded)
            assert args[0]["prior_summary"] is None
            return False  # put also degraded
        raise AssertionError(f"Unexpected: {name}")

    fake_wf, _ = _make_fake_temporal(execute_activity_handler=handler)
    monkeypatch.setitem(sys.modules, "temporalio", SimpleNamespace(workflow=fake_wf))
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)

    result = await step_compilers.compile_agent_invoke_step(decl, ctx)

    assert result == {"content": "degraded result"}
