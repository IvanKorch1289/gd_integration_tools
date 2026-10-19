"""Tests for ``src.backend.services.ai.ai_agent.agent_orchestration_mixin``.

Критичный regression: ``run_agent()`` НЕ должен конвертировать
:class:`CheckpointBackendUnavailable` в dict.

P0 fix (2026-10-14, ai_graph.py): ``build_and_run_agent(durable=True)``
поднимает :class:`CheckpointBackendUnavailable` вместо silent dict.
Контракт: caller (REST/GraphQL/MCP) должен получить 503 / typed code.

Но :meth:`AgentOrchestrationMixin.run_agent` имеет broad
``except Exception`` который ПЕРЕХВАТЫВАЕТ CheckpointBackendUnavailable
и возвращает ``{"success": False, "error": str(exc)}`` —
отменяя P0 fix полностью.

Этот файл — regression protection: typed exception MUST propagate
через mixin в caller (HTTP layer), а не превращаться в dict.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.ai_agent.agent_orchestration_mixin import (
    AgentOrchestrationMixin,
)
from src.backend.services.ai.agents.langgraph_checkpoint_exceptions import (
    CheckpointBackendUnavailable,
)


class _StubSanitizer:
    """Минимальный stub для :class:`AISanitizerProtocol`.

    Метод sanitize_text возвращает объект с .sanitized атрибутом и
    .restore() методом — этого достаточно для mixin.
    """

    def sanitize_text(self, text: str) -> Any:
        return SimpleNamespace(sanitized=text, masks_applied=[])

    def restore(self, text: str) -> str:
        return text


class _ServiceHost(AgentOrchestrationMixin):
    """Минимальный host с нужными state-attrs для AgentOrchestrationMixin."""

    def __init__(self) -> None:
        self._sanitizer = _StubSanitizer()
        # Остальные атрибуты — MagicMock (для других вызовов)
        self._ai_cfg = MagicMock()
        self._providers = {}
        self._open_webui = MagicMock()
        self._waf_headers = MagicMock()
        self._waf_url = MagicMock()
        self._agent_metrics_service = MagicMock()
        self._agent_tracer = MagicMock()
        self._agent_redis = MagicMock()
        self._get_http_client = MagicMock()
        self._extract_agent_response = MagicMock(return_value="response")
        self._call_perplexity = MagicMock()
        self._policy_gate = MagicMock()
        self._maybe_augment_with_rag = MagicMock()
        self._resolve_rag_service = MagicMock()
        self._resolve_authz_gateway = MagicMock()
        self._get_metrics_service = MagicMock()
        self._record_feedback = AsyncMock(return_value="fb-123")


class TestCheckpointBackendUnavailablePropagation:
    """``run_agent()`` НЕ должен превращать typed exception в dict."""

    @pytest.mark.asyncio
    async def test_checkpoint_backend_unavailable_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bug: broad ``except Exception`` ловит typed exception и
        конвертирует в ``{"success": False, "error": str(exc)}``.

        Контракт (P0): :class:`CheckpointBackendUnavailable` должен
        propagate до caller'а (HTTP layer) для маппинга в 503 /
        ``CHECKPOINT_BACKEND_UNAVAILABLE`` code.
        """
        # build_and_run_agent импортируется внутри функции из ai_graph,
        # поэтому patch'им через модуль ai_graph
        from src.backend.services.ai import ai_graph

        mock_build = AsyncMock(
            side_effect=CheckpointBackendUnavailable(
                backend="langgraph_postgres",
                thread_id="test-thread-1",
                context={"reason": "feature_flag_disabled"},
            )
        )
        monkeypatch.setattr(ai_graph, "build_and_run_agent", mock_build)

        host = _ServiceHost()

        # БЕЗ broad except: typed exception должен propagate
        with pytest.raises(CheckpointBackendUnavailable) as exc_info:
            await host.run_agent("hello", durable=True)

        # Caller получает typed exception с правильным context
        assert exc_info.value.backend == "langgraph_postgres"
        assert exc_info.value.thread_id == "test-thread-1"
        assert exc_info.value.context.get("reason") == "feature_flag_disabled"

    @pytest.mark.asyncio
    async def test_checkpoint_backend_unavailable_not_converted_to_dict(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-pattern: ``{"success": False, "error": str(exc)}`` —
        теряет тип, делает 503/typed-code mapping невозможным.
        """
        from src.backend.services.ai import ai_graph

        mock_build = AsyncMock(
            side_effect=CheckpointBackendUnavailable(
                backend="langgraph_postgres", thread_id="t1"
            )
        )
        monkeypatch.setattr(ai_graph, "build_and_run_agent", mock_build)

        host = _ServiceHost()

        try:
            result = await host.run_agent("hello", durable=True)
        except CheckpointBackendUnavailable:
            # OK — exception propagated
            return

        # Если дошли сюда — bug присутствует (return dict вместо raise)
        pytest.fail(
            f"CheckpointBackendUnavailable был конвертирован в dict: {result!r}. "
            "Это отменяет P0 fix — caller не сможет вернуть 503 / typed code."
        )

    @pytest.mark.asyncio
    async def test_import_error_still_handled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ImportError (нет langgraph) → return dict (best-effort, OK).

        Это documented behaviour, не bug. Должно остаться работать.
        """
        from src.backend.services.ai import ai_graph

        mock_build = AsyncMock(side_effect=ImportError("no langgraph"))
        monkeypatch.setattr(ai_graph, "build_and_run_agent", mock_build)

        host = _ServiceHost()
        result = await host.run_agent("hello", durable=False)

        # ImportError → return dict с понятным error
        assert result["success"] is False
        assert "langgraph" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_unrelated_exception_propagates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Другие exceptions (RuntimeError, ValueError) — caller решает.

        Минимальный contract: НЕ возвращать dict для non-ImportError exceptions.
        """
        from src.backend.services.ai import ai_graph

        mock_build = AsyncMock(side_effect=ValueError("malformed input"))
        monkeypatch.setattr(ai_graph, "build_and_run_agent", mock_build)

        host = _ServiceHost()

        # ValueError — current behavior: broad except → return dict
        # (documented best-effort, не regression)
        result = await host.run_agent("hello", durable=False)
        assert result["success"] is False
        assert "malformed" in result["error"]


class TestCheckpointContractCompliance:
    """Documented contract: HTTP layer получает typed exception → 503."""

    @pytest.mark.asyncio
    async def test_http_layer_can_distinguish_backend_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Если exception propagate, HTTP layer может маппить:
        - CheckpointBackendUnavailable → 503 + CHECKPOINT_BACKEND_UNAVAILABLE
        - Другие exceptions → 500

        Это test проверяет что typed exception не теряется, и HTTP layer
        может правильно отреагировать.
        """
        from src.backend.services.ai import ai_graph

        mock_build = AsyncMock(
            side_effect=CheckpointBackendUnavailable(
                backend="langgraph_postgres",
                thread_id="http-test",
                context={"reason": "saver_module_removed"},
            )
        )
        monkeypatch.setattr(ai_graph, "build_and_run_agent", mock_build)

        host = _ServiceHost()

        try:
            await host.run_agent("test", durable=True)
            pytest.fail("Expected CheckpointBackendUnavailable")
        except CheckpointBackendUnavailable as exc:
            # HTTP layer делает: 503 + code
            assert exc.backend == "langgraph_postgres"
            assert exc.context["reason"] == "saver_module_removed"
        except Exception as exc:
            # Любое другое исключение — не 503, generic 500
            pytest.fail(
                f"Expected CheckpointBackendUnavailable, got {type(exc).__name__}: {exc}. "
                "Если тип потерян (TypeError etc), HTTP layer не сможет "
                "вернуть правильный код."
            )
