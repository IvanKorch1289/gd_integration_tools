"""Тесты LangGraph агента с :class:`LiteLLMGateway`-backend.

Проверяют:
* :func:`build_chat_model` берёт конфигурацию из gateway (model, fallback);
* :func:`build_chat_model` поднимает ImportError если ChatLiteLLM недоступен;
* :func:`build_and_run_agent` корректно деградирует при отсутствии deps;
* gateway-параметры пробрасываются в ChatLiteLLM;
* :func:`build_and_run_agent` поднимает :class:`CheckpointBackendUnavailable`
  при ``durable=True`` без configured backend (P0 fix 2026-10-15).
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


@pytest.fixture()
def fake_litellm_gateway() -> Any:
    """Минимальная подмена :class:`LiteLLMGateway` для тестов."""
    return SimpleNamespace(
        _default_model="openai/gpt-4o-mini",
        _fallbacks=["anthropic/claude-sonnet-4-6", "local/llama-3-8b"],
        _timeout=30.0,
        _num_retries=2,
    )


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


def test_build_chat_model_override_model(
    fake_litellm_gateway: Any, fake_chat_litellm_module: dict[str, Any]
) -> None:
    """Явный model переопределяет gateway._default_model."""
    from src.backend.services.ai.ai_graph import build_chat_model

    llm = build_chat_model(
        gateway=fake_litellm_gateway, model="anthropic/claude-3-opus", temperature=0.0
    )
    assert llm is not None
    assert fake_chat_litellm_module["model"] == "anthropic/claude-3-opus"


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
    """build_and_run_agent создаёт ReAct-агента и возвращает финальный ответ.

    После P0 fix (2026-10-14) durable=False идёт через MemorySaver — мокаем
    ``langgraph.checkpoint.memory``, чтобы eager import не упал.
    """
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
    fake_lcm = ModuleType("langgraph.checkpoint")
    fake_lcm_m = ModuleType("langgraph.checkpoint.memory")
    captured_memory_saver: dict[str, Any] = {}

    class _FakeMemorySaver:
        def __init__(self) -> None:
            captured_memory_saver["called"] = True

    fake_lcm_m.MemorySaver = _FakeMemorySaver  # type: ignore[attr-defined]
    fake_lg.checkpoint = fake_lcm  # type: ignore[attr-defined]
    fake_lcm.memory = fake_lcm_m  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langgraph", fake_lg)
    monkeypatch.setitem(sys.modules, "langgraph.prebuilt", fake_lp)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint", fake_lcm)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.memory", fake_lcm_m)

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
    # durable=False → MemorySaver path (P0 fix, 2026-10-14).
    assert captured_memory_saver.get("called") is True
    assert captured_invoke["checkpointer"] is not None


# === P0 fix (2026-10-15): regression tests for CheckpointBackendUnavailable =====


def _mock_langgraph_with_memory_saver(
    monkeypatch: pytest.MonkeyPatch, captured_invoke: dict[str, Any] | None = None
) -> None:
    """Устанавливает полный langgraph mock: prebuilt + checkpoint.memory.

    captured_invoke (опц.): если задан, будет заполнен аргументами
    ``create_react_agent`` — для теста durable=False.
    """

    def _default_create_react_agent(llm: Any, tools: list[Any], **kwargs: Any) -> Any:
        if captured_invoke is not None:
            captured_invoke["llm_present"] = llm is not None
            captured_invoke["tools_count"] = len(tools)
            captured_invoke["checkpointer"] = kwargs.get("checkpointer")
            captured_invoke["max_iterations"] = kwargs.get("max_iterations")

        class _Agent:
            async def ainvoke(
                self, payload: dict[str, Any], config: dict[str, Any] | None = None
            ) -> dict[str, Any]:
                if captured_invoke is not None:
                    captured_invoke["payload"] = payload
                    captured_invoke["config"] = config
                return {"messages": [SimpleNamespace(content="ok")]}

        return _Agent()

    fake_lp = ModuleType("langgraph.prebuilt")
    fake_lp.create_react_agent = _default_create_react_agent  # type: ignore[attr-defined]
    fake_lcm = ModuleType("langgraph.checkpoint")
    fake_lcm_m = ModuleType("langgraph.checkpoint.memory")

    class _MemorySaver:
        def __init__(self) -> None:
            pass

    fake_lcm_m.MemorySaver = _MemorySaver  # type: ignore[attr-defined]
    fake_lg = ModuleType("langgraph")
    fake_lg.prebuilt = fake_lp  # type: ignore[attr-defined]
    fake_lg.checkpoint = fake_lcm  # type: ignore[attr-defined]
    fake_lcm.memory = fake_lcm_m  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langgraph", fake_lg)
    monkeypatch.setitem(sys.modules, "langgraph.prebuilt", fake_lp)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint", fake_lcm)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.memory", fake_lcm_m)


@pytest.mark.asyncio
async def test_checkpoint_backend_unavailable_raised_when_durable_no_backend(
    monkeypatch: pytest.MonkeyPatch, fake_chat_litellm_module: dict[str, Any]
) -> None:
    """P0 fix (2026-10-15): durable=True без configured backend поднимает
    :class:`CheckpointBackendUnavailable` (НЕ silent fallback).

    Без этого теста silent inversion (durable=True был слабее durable=False)
    может вернуться. Также проверяет, что broad ``except Exception``
    в ``build_and_run_agent`` НЕ проглатывает typed exception.
    """
    from src.backend.core.config.features import feature_flags as ff_mod

    monkeypatch.setattr(ff_mod, "langgraph_postgres_checkpoint", False)
    _mock_langgraph_with_memory_saver(monkeypatch)

    from src.backend.services.ai.agents.langgraph_checkpoint_exceptions import (
        CheckpointBackendUnavailable,
    )
    from src.backend.services.ai.ai_graph import build_and_run_agent

    with pytest.raises(CheckpointBackendUnavailable) as exc_info:
        await build_and_run_agent("hello", tool_actions=[], durable=True)
    assert exc_info.value.backend == "langgraph_postgres"
    assert exc_info.value.thread_id is None  # без явного thread_id
    assert exc_info.value.context.get("reason") == "feature_flag_disabled"


@pytest.mark.asyncio
async def test_checkpoint_backend_unavailable_with_thread_id(
    monkeypatch: pytest.MonkeyPatch, fake_chat_litellm_module: dict[str, Any]
) -> None:
    """P0 fix: ``thread_id`` попадает в exception context."""
    from src.backend.core.config.features import feature_flags as ff_mod

    monkeypatch.setattr(ff_mod, "langgraph_postgres_checkpoint", False)
    _mock_langgraph_with_memory_saver(monkeypatch)

    from src.backend.services.ai.agents.langgraph_checkpoint_exceptions import (
        CheckpointBackendUnavailable,
    )
    from src.backend.services.ai.ai_graph import build_and_run_agent

    with pytest.raises(CheckpointBackendUnavailable) as exc_info:
        await build_and_run_agent(
            "hello", tool_actions=[], durable=True, session_id="test-thread-1"
        )
    assert exc_info.value.thread_id == "test-thread-1"


@pytest.mark.asyncio
async def test_durable_false_uses_memory_saver(
    monkeypatch: pytest.MonkeyPatch,
    fake_litellm_gateway: Any,
    fake_chat_litellm_module: dict[str, Any],
) -> None:
    """P0 fix: durable=False идёт через MemorySaver (НЕ silent None checkpointer).

    Проверяет, что inversion не возвращается: ``durable=False`` создаёт
    реальный MemorySaver, который попадает в ``create_react_agent``.
    """
    captured: dict[str, Any] = {}
    _mock_langgraph_with_memory_saver(monkeypatch, captured_invoke=captured)

    from src.backend.services.ai.ai_graph import build_and_run_agent

    result = await build_and_run_agent(
        "prompt-durable-false",
        tool_actions=[],
        durable=False,
        gateway=fake_litellm_gateway,
    )
    assert "error" not in result
    assert result["prompt"] == "prompt-durable-false"
    # checkpointer не None (это инстанс MemorySaver, не None)
    assert captured["checkpointer"] is not None


@pytest.mark.asyncio
async def test_checkpoint_backend_unavailable_propagates_through_generic_handler(
    monkeypatch: pytest.MonkeyPatch, fake_chat_litellm_module: dict[str, Any]
) -> None:
    """P0 fix: broad ``except Exception`` НЕ конвертирует CheckpointBackend
    в ``{"error": str(exc)}`` dict.

    До этого теста broad except глотал typed exception, и caller получал
    dict вместо exception. Без propagation контракт «503 / CHECKPOINT_BACKEND
    _UNAVAILABLE» невозможен.
    """
    from src.backend.core.config.features import feature_flags as ff_mod

    monkeypatch.setattr(ff_mod, "langgraph_postgres_checkpoint", False)
    _mock_langgraph_with_memory_saver(monkeypatch)

    from src.backend.services.ai.agents.langgraph_checkpoint_exceptions import (
        CheckpointBackendUnavailable,
    )
    from src.backend.services.ai.ai_graph import build_and_run_agent

    # Если exception проглатывается, мы получим dict и ``pytest.raises``
    # провалится. Это и есть regression protection.
    with pytest.raises(CheckpointBackendUnavailable):
        await build_and_run_agent("hello", tool_actions=[], durable=True)


async def test_saver_removed_error_message_does_not_suggest_git_checkout(
    monkeypatch: pytest.MonkeyPatch, fake_chat_litellm_module: dict[str, Any]
) -> None:
    """Regression: when ``langgraph_postgres_checkpoint=True`` but saver is
    removed, error context must NOT instruct the user to ``git checkout`` an
    old commit.

    Раньше context содержал ``"fix": "git checkout 00cba5a71~1 to restore
    langgraph_postgres_saver.py"`` — это misleading fix (saver удалён по
    design, восстанавливать нельзя) и нарушение integrity: рекомендовать
    restore deleted code как fix делает систему хрупкой.

    Корректное поведение: error context указывает на root cause
    (``saver_module_removed``) и направляет на feature flag / durable flag,
    но НЕ предлагает восстанавливать удалённый код.
    """
    from src.backend.core.config.features import feature_flags as ff_mod

    # Включаем flag (иначе первая ветка вернёт "feature_flag_disabled")
    monkeypatch.setattr(ff_mod, "langgraph_postgres_checkpoint", True)
    _mock_langgraph_with_memory_saver(monkeypatch)

    from src.backend.services.ai.agents.langgraph_checkpoint_exceptions import (
        CheckpointBackendUnavailable,
    )
    from src.backend.services.ai.ai_graph import build_and_run_agent

    with pytest.raises(CheckpointBackendUnavailable) as exc_info:
        await build_and_run_agent("hello", tool_actions=[], durable=True)

    # Восстанавливаем original state
    monkeypatch.setattr(ff_mod, "langgraph_postgres_checkpoint", False)

    # Context должен указывать root cause
    assert exc_info.value.context.get("reason") == "saver_module_removed"

    # НО не должен предлагать git checkout (integrity + misleading fix)
    fix_msg = str(exc_info.value.context.get("fix", ""))
    assert "git checkout" not in fix_msg.lower(), (
        f"Error context suggests `git checkout` as fix — это misleading: "
        f"saver удалён по design, восстанавливать нельзя. "
        f"Got: {fix_msg!r}"
    )
    assert "restore" not in fix_msg.lower() or "do not" in fix_msg.lower(), (
        f"Error context suggests `restore` as fix — misleading. "
        f"Got: {fix_msg!r}"
    )
