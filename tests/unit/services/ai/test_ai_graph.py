"""Тесты LangGraph агента с :class:`LiteLLMGateway`-backend.

Проверяют:
* :func:`build_chat_model` берёт конфигурацию из gateway (model, fallback);
* :func:`build_chat_model` поднимает ImportError если ChatLiteLLM недоступен;
* :func:`build_and_run_agent` корректно деградирует при отсутствии deps;
* gateway-параметры пробрасываются в ChatLiteLLM.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


@pytest.fixture()
def fake_litellm_gateway() -> Any:
    """Минимальная подмена :class:`LiteLLMGateway` для тестов."""
    gw = SimpleNamespace(
        _default_model="openai/gpt-4o-mini",
        _fallbacks=["anthropic/claude-sonnet-4-6", "local/llama-3-8b"],
        _timeout=30.0,
        _num_retries=2,
    )
    return gw


@pytest.fixture()
def fake_chat_litellm_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Монтирует фейковый ``langchain_litellm`` в sys.modules."""
    captured: dict[str, Any] = {}

    class _FakeChatLiteLLM:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self.kwargs = kwargs

    fake_mod = ModuleType("langchain_litellm")
    fake_mod.ChatLiteLLM = _FakeChatLiteLLM  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_litellm", fake_mod)
    return captured


def test_build_chat_model_propagates_gateway_settings(
    fake_litellm_gateway: Any, fake_chat_litellm_module: dict[str, Any]
) -> None:
    """``build_chat_model`` должен взять model + fallbacks + timeout из gateway."""
    from src.backend.services.ai.ai_graph import build_chat_model

    llm = build_chat_model(gateway=fake_litellm_gateway, temperature=0.0)
    assert llm is not None
    assert fake_chat_litellm_module["model"] == "openai/gpt-4o-mini"
    assert fake_chat_litellm_module["temperature"] == 0.0
    assert fake_chat_litellm_module["request_timeout"] == 30.0
    assert fake_chat_litellm_module["num_retries"] == 2
    assert fake_chat_litellm_module["fallbacks"] == [
        "anthropic/claude-sonnet-4-6",
        "local/llama-3-8b",
    ]


def test_build_chat_model_no_fallbacks(
    monkeypatch: pytest.MonkeyPatch, fake_chat_litellm_module: dict[str, Any]
) -> None:
    """Если fallback-list пустой — ключ 'fallbacks' не передаётся."""
    from src.backend.services.ai.ai_graph import build_chat_model

    gw = SimpleNamespace(
        _default_model="openai/gpt-4o-mini",
        _fallbacks=[],
        _timeout=10.0,
        _num_retries=1,
    )
    llm = build_chat_model(gateway=gw, temperature=0.2)
    assert llm is not None
    assert "fallbacks" not in fake_chat_litellm_module
    assert fake_chat_litellm_module["temperature"] == 0.2


def test_build_chat_model_falls_back_to_community(
    monkeypatch: pytest.MonkeyPatch, fake_litellm_gateway: Any
) -> None:
    """При отсутствии ``langchain_litellm`` подхватывается ``langchain_community``."""
    monkeypatch.setitem(sys.modules, "langchain_litellm", None)
    # При попытке `from langchain_litellm import ...` Python увидит None и кинет ImportError
    sys.modules.pop("langchain_litellm", None)

    captured: dict[str, Any] = {}

    class _CommunityChatLiteLLM:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_community = ModuleType("langchain_community")
    fake_chat_models = ModuleType("langchain_community.chat_models")
    fake_chat_models.ChatLiteLLM = _CommunityChatLiteLLM
    fake_community.chat_models = fake_chat_models
    monkeypatch.setitem(sys.modules, "langchain_community", fake_community)
    monkeypatch.setitem(
        sys.modules, "langchain_community.chat_models", fake_chat_models
    )

    from src.backend.services.ai.ai_graph import build_chat_model

    llm = build_chat_model(gateway=fake_litellm_gateway)
    assert llm is not None
    assert captured["model"] == "openai/gpt-4o-mini"


def test_build_chat_model_raises_when_no_adapter(
    monkeypatch: pytest.MonkeyPatch, fake_litellm_gateway: Any
) -> None:
    """Если ни langchain-litellm ни langchain_community нет — ImportError."""
    # Гарантируем отсутствие обоих модулей.
    sys.modules.pop("langchain_litellm", None)
    sys.modules.pop("langchain_community", None)
    sys.modules.pop("langchain_community.chat_models", None)
    monkeypatch.setitem(sys.modules, "langchain_litellm", None)
    monkeypatch.setitem(sys.modules, "langchain_community", None)
    monkeypatch.setitem(sys.modules, "langchain_community.chat_models", None)
    sys.modules.pop("langchain_litellm", None)
    sys.modules.pop("langchain_community", None)
    sys.modules.pop("langchain_community.chat_models", None)

    from src.backend.services.ai.ai_graph import build_chat_model

    with pytest.raises(ImportError) as exc_info:
        build_chat_model(gateway=fake_litellm_gateway)
    assert "ChatLiteLLM" in str(exc_info.value)


@pytest.mark.asyncio
async def test_build_and_run_agent_returns_error_when_deps_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """build_and_run_agent корректно деградирует при отсутствии LangGraph."""
    sys.modules.pop("langgraph", None)
    sys.modules.pop("langgraph.prebuilt", None)
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.prebuilt", None)

    from src.backend.services.ai.ai_graph import build_and_run_agent

    result = await build_and_run_agent("hello", tool_actions=[])
    assert "error" in result
    assert "не установлены" in result["error"] or "Зависимости" in result["error"]


@pytest.mark.asyncio
async def test_build_and_run_agent_invokes_react(
    monkeypatch: pytest.MonkeyPatch,
    fake_litellm_gateway: Any,
    fake_chat_litellm_module: dict[str, Any],
) -> None:
    """build_and_run_agent создаёт ReAct-агента и возвращает финальный ответ."""
    captured_invoke: dict[str, Any] = {}

    class _FakeAgent:
        async def ainvoke(
            self, payload: dict[str, Any], config: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            captured_invoke.update(payload)
            captured_invoke["config"] = config
            return {"messages": [SimpleNamespace(content="ok-final")]}

    def _fake_create_react_agent(
        llm: Any, tools: list[Any], **kwargs: Any
    ) -> _FakeAgent:
        captured_invoke["llm_present"] = llm is not None
        captured_invoke["tools_count"] = len(tools)
        captured_invoke["checkpointer"] = kwargs.get("checkpointer")
        captured_invoke["max_iterations"] = kwargs.get("max_iterations")
        return _FakeAgent()

    fake_lp = ModuleType("langgraph.prebuilt")
    fake_lp.create_react_agent = _fake_create_react_agent  # type: ignore[attr-defined]
    fake_lg = ModuleType("langgraph")
    fake_lg.prebuilt = fake_lp  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langgraph", fake_lg)
    monkeypatch.setitem(sys.modules, "langgraph.prebuilt", fake_lp)

    from src.backend.services.ai.ai_graph import build_and_run_agent

    result = await build_and_run_agent(
        "test prompt", tool_actions=[], gateway=fake_litellm_gateway
    )
    assert result["prompt"] == "test prompt"
    assert result["response"] == "ok-final"
    assert result["message_count"] == 1
    assert captured_invoke["llm_present"] is True
    assert captured_invoke["tools_count"] == 0
    assert captured_invoke["max_iterations"] == 10
    assert captured_invoke["config"] is not None
    assert "thread_id" in (captured_invoke["config"].get("configurable") or {})
    # Проверяем что ChatLiteLLM был сконструирован с параметрами из gateway.
    assert fake_chat_litellm_module["model"] == "openai/gpt-4o-mini"
