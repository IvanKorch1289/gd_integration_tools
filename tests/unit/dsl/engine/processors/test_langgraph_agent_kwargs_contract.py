"""Tests for ``src.backend.dsl.engine.processors.agent_dsl.langgraph_agent``.

Критичный regression: ``LangGraphAgentProcessor.process()`` вызывает
``build_and_run_agent`` с НЕПРАВИЛЬНЫМИ kwarg names:
- ``query=`` (нет такого параметра; должно быть ``prompt=``)
- ``thread_id=`` (нет такого параметра; должно быть ``session_id=``)
- ``max_iterations=`` (нет такого параметра; build_and_run_agent не принимает)
- Нет ``tool_actions=`` (обязательный параметр)

Это masked by ``# type: ignore[call-arg]``. Существующий тест
``test_invoke_calls_build_and_run_agent`` mock'ает ``build_and_run_agent``,
поэтому bad kwargs не валидируются — баг невидим.

Реальный runtime: ``TypeError: build_and_run_agent() got an unexpected
keyword argument 'query'`` при вызове DSL step.

Этот файл — regression protection: kwargs match реальный signature.
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _bypass_auth() -> None:
    """LangGraphAgentProcessor требует capability=agent.run — bypass в unit-тестах."""
    from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
        LangGraphAgentProcessor,
    )

    LangGraphAgentProcessor.auth_check = AsyncMock(  # type: ignore[method-assign]
        return_value=True
    )


class TestLangGraphAgentProcessorKwargs:
    """``process()`` должен передавать в ``build_and_run_agent`` только
    параметры из её реальной signature.
    """

    @pytest.mark.asyncio
    async def test_kwargs_match_build_and_run_agent_signature(self) -> None:
        """Bug: ``langgraph_agent.py`` вызывает ``build_and_run_agent`` с
        неправильными kwarg names. Это приводит к ``TypeError`` при
        реальном вызове (если build_and_run_agent не замокан).
        """
        from src.backend.services.ai.ai_graph import build_and_run_agent
        from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
            LangGraphAgentProcessor,
        )

        # Реальный signature — source of truth
        real_sig = inspect.signature(build_and_run_agent)
        real_params = set(real_sig.parameters.keys())

        # Capture kwargs через side_effect
        captured_kwargs: dict[str, object] = {}

        async def capture(*args: object, **kwargs: object) -> dict[str, object]:
            captured_kwargs.update(kwargs)
            return {"output": "captured"}

        # Замокаем build_and_run_agent в source module
        from src.backend.services.ai import ai_graph

        original = ai_graph.build_and_run_agent
        ai_graph.build_and_run_agent = capture  # type: ignore[assignment]
        try:
            p = LangGraphAgentProcessor(query="hello", to="body.answer")
            ex = MagicMock()
            ex.in_message.body = {}
            ex.set_property = MagicMock()
            ctx = MagicMock()

            try:
                await p.process(ex, ctx)
            except TypeError as exc:
                # Если kwargs неверные — TypeError
                pytest.fail(
                    f"LangGraphAgentProcessor вызвал build_and_run_agent с "
                    f"неправильными kwargs: {captured_kwargs}. "
                    f"Реальный signature: {real_params}. "
                    f"Error: {exc}"
                )
        finally:
            ai_graph.build_and_run_agent = original  # type: ignore[assignment]

        # Все переданные kwargs должны быть в реальной signature
        bad_kwargs = set(captured_kwargs.keys()) - real_params
        assert not bad_kwargs, (
            f"LangGraphAgentProcessor передаёт kwargs которых нет в "
            f"build_and_run_agent: {bad_kwargs}. "
            f"Реальный signature: {real_params}"
        )

    @pytest.mark.asyncio
    async def test_required_param_tool_actions_is_passed(self) -> None:
        """``tool_actions`` — обязательный параметр build_and_run_agent.

        LangGraphAgentProcessor должен передавать ``tool_actions=`` (даже
        если пустой list) для корректного вызова.
        """
        from src.backend.services.ai import ai_graph
        from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
            LangGraphAgentProcessor,
        )

        captured_kwargs: dict[str, object] = {}

        async def capture(*args: object, **kwargs: object) -> dict[str, object]:
            captured_kwargs.update(kwargs)
            return {"output": "ok"}

        original = ai_graph.build_and_run_agent
        ai_graph.build_and_run_agent = capture  # type: ignore[assignment]
        try:
            p = LangGraphAgentProcessor(query="hello", to="body.answer")
            ex = MagicMock()
            ex.in_message.body = {}
            ex.set_property = MagicMock()
            ctx = MagicMock()

            try:
                await p.process(ex, ctx)
            except TypeError as exc:
                pytest.fail(
                    f"Process упал с TypeError: {exc}. "
                    f"Вероятно пропущен обязательный параметр tool_actions."
                )
        finally:
            ai_graph.build_and_run_agent = original  # type: ignore[assignment]

        assert "tool_actions" in captured_kwargs, (
            f"tool_actions — обязательный параметр build_and_run_agent, "
            f"но LangGraphAgentProcessor его НЕ передаёт. "
            f"Переданные kwargs: {set(captured_kwargs.keys())}"
        )

    @pytest.mark.asyncio
    async def test_query_passed_as_prompt_not_query(self) -> None:
        """``query=self.query`` → должен быть ``prompt=self.query``.

        Старое имя параметра — bug. Правильное имя — ``prompt``.
        """
        from src.backend.services.ai import ai_graph
        from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
            LangGraphAgentProcessor,
        )

        captured_kwargs: dict[str, object] = {}

        async def capture(*args: object, **kwargs: object) -> dict[str, object]:
            captured_kwargs.update(kwargs)
            return {"output": "ok"}

        original = ai_graph.build_and_run_agent
        ai_graph.build_and_run_agent = capture  # type: ignore[assignment]
        try:
            p = LangGraphAgentProcessor(query="test_query_value", to="body.answer")
            ex = MagicMock()
            ex.in_message.body = {}
            ex.set_property = MagicMock()
            ctx = MagicMock()

            try:
                await p.process(ex, ctx)
            except TypeError as exc:
                pytest.fail(f"TypeError: {exc}")
        finally:
            ai_graph.build_and_run_agent = original  # type: ignore[assignment]

        # Должен быть `prompt` (не `query`)
        assert "prompt" in captured_kwargs, (
            f"build_and_run_agent ожидает 'prompt' kwarg, не 'query'. "
            f"Переданные kwargs: {set(captured_kwargs.keys())}"
        )
        assert captured_kwargs.get("prompt") == "test_query_value", (
            f"prompt должен содержать значение self.query. "
            f"Got: {captured_kwargs.get('prompt')!r}"
        )
        assert "query" not in captured_kwargs, (
            f"'query' НЕ является параметром build_and_run_agent. "
            f"Должен быть 'prompt'. Переданные: {set(captured_kwargs.keys())}"
        )

    @pytest.mark.asyncio
    async def test_thread_id_passed_as_session_id(self) -> None:
        """``thread_id=self.thread_id`` → должен быть ``session_id=self.thread_id``.

        build_and_run_agent не принимает ``thread_id`` (это параметр
        LangGraph checkpointer, не нашего wrapper).
        """
        from src.backend.services.ai import ai_graph
        from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
            LangGraphAgentProcessor,
        )

        captured_kwargs: dict[str, object] = {}

        async def capture(*args: object, **kwargs: object) -> dict[str, object]:
            captured_kwargs.update(kwargs)
            return {"output": "ok"}

        original = ai_graph.build_and_run_agent
        ai_graph.build_and_run_agent = capture  # type: ignore[assignment]
        try:
            p = LangGraphAgentProcessor(
                query="test", thread_id="my-thread-id", to="body.answer"
            )
            ex = MagicMock()
            ex.in_message.body = {}
            ex.set_property = MagicMock()
            ctx = MagicMock()

            try:
                await p.process(ex, ctx)
            except TypeError as exc:
                pytest.fail(f"TypeError: {exc}")
        finally:
            ai_graph.build_and_run_agent = original  # type: ignore[assignment]

        assert "thread_id" not in captured_kwargs, (
            f"'thread_id' НЕ является параметром build_and_run_agent. "
            f"Должен быть 'session_id'. Переданные: {set(captured_kwargs.keys())}"
        )
        assert captured_kwargs.get("session_id") == "my-thread-id", (
            f"session_id должен содержать значение self.thread_id. "
            f"Got: {captured_kwargs.get('session_id')!r}"
        )
