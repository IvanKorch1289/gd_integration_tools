"""P2 (2026-10-15) audit: targeted exception review для build_and_run_agent.

Audit P2 говорит: «Следующий PR — максимум один boundary: plugin
sandbox ИЛИ Temporal Activity ИЛИ RPA page execution ИЛИ agent tool».
Выбираем **agent tool execution boundary** в
:func:`build_and_run_agent <services.ai.ai_graph.build_and_run_agent>`.

Текущий код::

    try:
        ...  # agent build, ainvoke, message extraction
    except ImportError as exc:
        return {"error": ...}
    except CheckpointBackendUnavailable:
        raise  # P0 fix (2026-10-15)
    except Exception as exc:
        return {"error": str(exc)}

Проблема: broad ``except Exception`` конвертирует ВСЕ ошибки
agent execution (включая ``KeyError`` из missing tools, ``ValueError``
из LLM response, ``TimeoutError`` из network) в ``{"error": str(exc)}``.
Caller не может различать типы ошибок, retry logic работает
вслепую, audit-trail теряет контекст.

Минимально-совместимое исправление (этот PR):

1. **Re-raise KeyError** (action/tool missing) — caller уже знает
   как его обработать (см. test_action_six_protocols), не должно
   превращаться в dict;
2. **Re-raise CancelledError** (timeout отменён) — должен
   пробрасываться как CancelledError, не dict;
3. **Re-raise ValueError** (LLM response malformed) — caller
   решает retry vs DLQ;
4. **ВСЁ ОСТАЛЬНОЕ** остаётся в broad except → dict (backward-compat);
5. **Regression tests** для каждой typed re-raise.

Не делаем: новый AgentExecutionError, retry-framework, DLQ. Только
re-raise критичных typed exceptions + tests.
"""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

# ─────────────────────────── fixtures ───────────────────────────


@pytest.fixture
def fake_litellm_gateway() -> Any:
    return SimpleNamespace(
        _default_model="openai/gpt-4o-mini",
        _fallbacks=[],
        _timeout=10.0,
        _num_retries=1,
    )


@pytest.fixture
def fake_chat_litellm_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    captured: dict[str, Any] = {}

    class _FakeChatLiteLLM:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_mod = ModuleType("langchain_litellm")
    fake_mod.ChatLiteLLM = _FakeChatLiteLLM  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_litellm", fake_mod)
    return captured


def _mock_langgraph_with_failing_agent(
    monkeypatch: pytest.MonkeyPatch, exc_to_raise: Exception
) -> dict[str, Any]:
    """Fake ``create_react_agent`` который бросает ``exc_to_raise`` в ainvoke.

    MemorySaver мокается для non-durable path (build_and_run_agent
    с durable=False создаёт MemorySaver).
    """
    captured: dict[str, Any] = {}

    class _FailingAgent:
        async def ainvoke(
            self, payload: dict[str, Any], config: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            raise exc_to_raise

    def _fake_create(llm: Any, tools: list[Any], **kwargs: Any) -> _FailingAgent:
        captured["checkpointer"] = kwargs.get("checkpointer")
        return _FailingAgent()

    fake_lp = ModuleType("langgraph.prebuilt")
    fake_lp.create_react_agent = _fake_create  # type: ignore[attr-defined]
    fake_lcm = ModuleType("langgraph.checkpoint")
    fake_lcm_m = ModuleType("langgraph.checkpoint.memory")

    class _MemorySaver:
        def __init__(self) -> None:
            captured["memory_saver"] = True

    fake_lcm_m.MemorySaver = _MemorySaver  # type: ignore[attr-defined]
    fake_lg = ModuleType("langgraph")
    fake_lg.prebuilt = fake_lp  # type: ignore[attr-defined]
    fake_lg.checkpoint = fake_lcm  # type: ignore[attr-defined]
    fake_lcm.memory = fake_lcm_m  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langgraph", fake_lg)
    monkeypatch.setitem(sys.modules, "langgraph.prebuilt", fake_lp)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint", fake_lcm)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.memory", fake_lcm_m)
    return captured


# ─────────────────────────── tests ───────────────────────────


class TestAgentExceptionBoundary:
    """``build_and_run_agent`` exception boundary contract (P2, 2026-10-15)."""

    @pytest.mark.asyncio
    async def test_key_error_propagates_not_swallowed_to_dict(
        self,
        fake_litellm_gateway: Any,
        fake_chat_litellm_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``KeyError`` из agent ainvoke ПРОБРАСЫВАЕТСЯ, не dict.

        Audit P2: «re-raise typed exception для KeyError».
        KeyError обычно означает missing tool/action — caller
        знает как обработать (401/404/HTTP). Broad except
        превращал в ``{"error": "..."}`` dict, теряя тип.
        """
        _mock_langgraph_with_failing_agent(
            monkeypatch, KeyError("'tool.missing.action'")
        )
        from src.backend.services.ai.ai_graph import build_and_run_agent

        with pytest.raises(KeyError) as exc_info:
            await build_and_run_agent(
                "test key error", tool_actions=[], gateway=fake_litellm_gateway
            )
        assert "tool.missing.action" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_not_swallowed(
        self,
        fake_litellm_gateway: Any,
        fake_chat_litellm_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``CancelledError`` (timeout) ПРОБРАСЫВАЕТСЯ, не dict.

        Audit P2: «timeout/max iterations». asyncio.CancelledError
        нельзя swallow'ить — это часть cancellation protocol.
        Caller должен видеть CancelledError чтобы решить: retry,
        propagate, или abort request.
        """
        _mock_langgraph_with_failing_agent(monkeypatch, asyncio.CancelledError())
        from src.backend.services.ai.ai_graph import build_and_run_agent

        with pytest.raises(asyncio.CancelledError):
            await build_and_run_agent(
                "test cancelled", tool_actions=[], gateway=fake_litellm_gateway
            )

    @pytest.mark.asyncio
    async def test_value_error_propagates_not_swallowed(
        self,
        fake_litellm_gateway: Any,
        fake_chat_litellm_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ValueError`` (LLM response malformed) ПРОБРАСЫВАЕТСЯ.

        Audit P2: «ValueError → caller решает retry vs DLQ».
        LLM может вернуть malformed response → ValueError
        при parse. Caller (route orchestrator) решает retry
        strategy. Dict возврат скрывает тип.
        """
        _mock_langgraph_with_failing_agent(
            monkeypatch, ValueError("malformed LLM response")
        )
        from src.backend.services.ai.ai_graph import build_and_run_agent

        with pytest.raises(ValueError) as exc_info:
            await build_and_run_agent(
                "test value error", tool_actions=[], gateway=fake_litellm_gateway
            )
        assert "malformed LLM response" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_runtime_error_returns_dict_for_backward_compat(
        self,
        fake_litellm_gateway: Any,
        fake_chat_litellm_module: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``RuntimeError`` (other) остаётся dict — backward-compat.

        Audit P2: «ВСЁ ОСТАЛЬНОЕ остаётся в broad except → dict».
        Не делаем mass-rewrite. Только critical types (KeyError,
        CancelledError, ValueError, CheckpointBackendUnavailable)
        получают typed propagation. RuntimeError остаётся dict
        для backward compat с существующим caller code.
        """
        _mock_langgraph_with_failing_agent(
            monkeypatch, RuntimeError("transient LLM API error")
        )
        from src.backend.services.ai.ai_graph import build_and_run_agent

        result = await build_and_run_agent(
            "test runtime error", tool_actions=[], gateway=fake_litellm_gateway
        )
        # dict backward-compat
        assert "error" in result, f"Expected error dict, got: {result}"
        assert "transient LLM API error" in result["error"]
