"""Tests for ``src.backend.services.ai.agent_sandbox._process_pool``.

Критичный regression: ``ProcessPoolAgentSandbox.run_react()`` НЕ должен
конвертировать :class:`CheckpointBackendUnavailable` в
:class:`AgentSandboxResult(success=False)`.

Bug: broad ``except Exception`` (ранее) ловил :class:`CheckpointBackendUnavailable`
(он subclass of Exception) и возвращал :class:`AgentSandboxResult`
с success=False — отменяя P0 fix из ``ai_graph.py``.

Этот файл — regression protection: typed exception MUST propagate
через sandbox boundary в caller.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.ai.agent_sandbox_protocol import AgentSandboxResult
from src.backend.services.ai.agent_sandbox._process_pool import (
    ProcessPoolAgentSandbox,
)
from src.backend.services.ai.agents.langgraph_checkpoint_exceptions import (
    CheckpointBackendUnavailable,
)


class TestCheckpointBackendUnavailablePropagation:
    """``run_react()`` НЕ должен превращать typed exception в AgentSandboxResult."""

    @pytest.mark.asyncio
    async def test_checkpoint_backend_unavailable_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bug: broad ``except Exception`` ловил typed exception и
        конвертировал в AgentSandboxResult(success=False).

        Контракт (P0): :class:`CheckpointBackendUnavailable` должен
        propagate до caller'а (HTTP layer) для маппинга в 503 /
        ``CHECKPOINT_BACKEND_UNAVAILABLE`` code.
        """
        from src.backend.services.ai.agent_sandbox import _process_pool

        # Мокаем _sync_run_react чтобы бросить typed exception
        def _raise_checkpoint(*args, **kwargs):
            raise CheckpointBackendUnavailable(
                backend="langgraph_postgres",
                thread_id="sandbox-test-1",
                context={"reason": "feature_flag_disabled"},
            )

        monkeypatch.setattr(_process_pool, "_sync_run_react", _raise_checkpoint)

        # Мокаем loop.run_in_executor чтобы не создавать реальный executor
        async def fake_run_in_executor(executor, func, *args):
            return func(*args)  # прямой вызов поднятой функции

        monkeypatch.setattr(
            "asyncio.get_running_loop",
            lambda: MagicMock(run_in_executor=fake_run_in_executor),
        )

        # Мокаем asyncio.wait_for
        async def fake_wait_for(coro, timeout):
            return await coro

        monkeypatch.setattr(
            _process_pool.asyncio, "wait_for", fake_wait_for
        )

        sandbox = ProcessPoolAgentSandbox()

        # БЕЗ broad except: typed exception должен propagate
        with pytest.raises(CheckpointBackendUnavailable) as exc_info:
            await sandbox.run_react(
                prompt="hello",
                tool_actions=[],
                model="gpt-4",
                temperature=0.0,
                durable=True,
                session_id="s1",
            )

        # Caller получает typed exception с правильным context
        assert exc_info.value.backend == "langgraph_postgres"
        assert exc_info.value.thread_id == "sandbox-test-1"
        assert exc_info.value.context.get("reason") == "feature_flag_disabled"

    @pytest.mark.asyncio
    async def test_checkpoint_backend_unavailable_not_converted_to_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-pattern: AgentSandboxResult(success=False, data={...}) —
        теряет тип, делает 503/typed-code mapping невозможным.
        """
        from src.backend.services.ai.agent_sandbox import _process_pool

        def _raise_checkpoint(*args, **kwargs):
            raise CheckpointBackendUnavailable(
                backend="langgraph_postgres", thread_id="t1"
            )

        monkeypatch.setattr(_process_pool, "_sync_run_react", _raise_checkpoint)

        async def fake_run_in_executor(executor, func, *args):
            return func(*args)

        monkeypatch.setattr(
            "asyncio.get_running_loop",
            lambda: MagicMock(run_in_executor=fake_run_in_executor),
        )

        async def fake_wait_for(coro, timeout):
            return await coro

        monkeypatch.setattr(
            _process_pool.asyncio, "wait_for", fake_wait_for
        )

        sandbox = ProcessPoolAgentSandbox()

        try:
            result = await sandbox.run_react(
                prompt="hello",
                tool_actions=[],
                model="gpt-4",
                temperature=0.0,
                durable=True,
                session_id="s1",
            )
        except CheckpointBackendUnavailable:
            # OK — exception propagated
            return

        # Если дошли сюда — bug присутствует (return result вместо raise)
        pytest.fail(
            f"CheckpointBackendUnavailable был конвертирован в AgentSandboxResult: {result!r}. "
            "Это отменяет P0 fix — caller не сможет вернуть 503 / typed code."
        )

    @pytest.mark.asyncio
    async def test_timeout_error_still_returns_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TimeoutError → return result (documented behavior, не bug).

        Только CheckpointBackendUnavailable должна propagate, остальные
        exceptions (TimeoutError) → return result.
        """
        from src.backend.services.ai.agent_sandbox import _process_pool

        async def fake_wait_for(coro, timeout):
            raise TimeoutError("wall_time exceeded")

        monkeypatch.setattr(
            _process_pool.asyncio, "wait_for", fake_wait_for
        )

        sandbox = ProcessPoolAgentSandbox()
        result = await sandbox.run_react(
            prompt="hello",
            tool_actions=[],
            model="gpt-4",
            temperature=0.0,
            durable=False,
            session_id="s1",
        )

        assert isinstance(result, AgentSandboxResult)
        assert result.success is False
        assert "wall_time_exceeded" in str(result.data.get("error", ""))


class TestCheckpointContractCompliance:
    """Documented contract: HTTP layer получает typed exception → 503."""

    @pytest.mark.asyncio
    async def test_http_layer_can_distinguish_backend_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если exception propagate, HTTP layer может маппить:
        - CheckpointBackendUnavailable → 503 + CHECKPOINT_BACKEND_UNAVAILABLE
        - Другие exceptions → 500
        """
        from src.backend.services.ai.agent_sandbox import _process_pool

        def _raise_checkpoint(*args, **kwargs):
            raise CheckpointBackendUnavailable(
                backend="langgraph_postgres",
                thread_id="http-test",
                context={"reason": "saver_module_removed"},
            )

        monkeypatch.setattr(_process_pool, "_sync_run_react", _raise_checkpoint)

        async def fake_run_in_executor(executor, func, *args):
            return func(*args)

        monkeypatch.setattr(
            "asyncio.get_running_loop",
            lambda: MagicMock(run_in_executor=fake_run_in_executor),
        )

        async def fake_wait_for(coro, timeout):
            return await coro

        monkeypatch.setattr(
            _process_pool.asyncio, "wait_for", fake_wait_for
        )

        sandbox = ProcessPoolAgentSandbox()

        try:
            await sandbox.run_react(
                prompt="test",
                tool_actions=[],
                model="gpt-4",
                temperature=0.0,
                durable=True,
                session_id="s1",
            )
            pytest.fail("Expected CheckpointBackendUnavailable")
        except CheckpointBackendUnavailable as exc:
            # HTTP layer делает: 503 + code
            assert exc.backend == "langgraph_postgres"
            assert exc.context["reason"] == "saver_module_removed"
        except Exception as exc:
            # Любое другое исключение — не 503, generic 500
            pytest.fail(
                f"Expected CheckpointBackendUnavailable, got {type(exc).__name__}: {exc}. "
                "Если тип потерян, HTTP layer не сможет вернуть правильный код."
            )
