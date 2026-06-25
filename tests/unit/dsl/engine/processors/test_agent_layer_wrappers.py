"""Tests for new DSL wrappers over libs (Sprint 170 S170 — agent layer).

Coverage:
- LangGraph agent invocation DSL (wraps services.ai.ai_graph.build_and_run_agent)
- RAG search DSL (wraps HybridRAGSearch.search)
- Prompt registry DSL (wraps PromptRegistry.get)
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLangGraphAgentDSL:
    @pytest.mark.asyncio
    async def test_processor_instantiates_with_query(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
            LangGraphAgentProcessor,
        )
        p = LangGraphAgentProcessor(query="What is 2+2?", to="body.answer")
        assert p.query == "What is 2+2?"
        assert p.target == "body.answer"
        assert "prompt_get" not in p.name  # processor name has langgraph_agent prefix

    @pytest.mark.asyncio
    async def test_invoke_calls_build_and_run_agent(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.langgraph_agent import (
            LangGraphAgentProcessor,
        )
        p = LangGraphAgentProcessor(query="test", to="body.answer")
        ex = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Mock the ai_graph.build_and_run_agent
        with patch(
            "src.backend.services.ai.ai_graph.build_and_run_agent",
            new=AsyncMock(return_value={"output": "result text"}),
        ):
            await p.process(ex, ctx)
        assert ex.in_message.body.get("answer") == "result text"


class TestRAGSearchDSL:
    @pytest.mark.asyncio
    async def test_processor_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.ai.rag_search import (
            RAGSearchProcessor,
        )
        p = RAGSearchProcessor(query="test", namespace="docs", to="body.docs")
        assert p.query == "test"
        assert p.namespace == "docs"

    @pytest.mark.asyncio
    async def test_search_calls_hybrid_rag(self) -> None:
        from src.backend.dsl.engine.processors.ai.rag_search import (
            RAGSearchProcessor,
        )
        p = RAGSearchProcessor(query="test", namespace="docs", to="body.docs")
        ex = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ctx = MagicMock()
        mock_search = AsyncMock(return_value=[{"text": "doc1", "score": 0.9}])
        # Patch HybridRAGSearch class
        mock_search_instance = MagicMock()
        mock_search_instance.search = mock_search
        with patch(
            "src.backend.services.ai.hybrid_rag.HybridRAGSearch",
            return_value=mock_search_instance,
        ):
            await p.process(ex, ctx)
        assert ex.in_message.body.get("docs") == [{"text": "doc1", "score": 0.9}]


class TestPromptRegistryDSL:
    def test_processor_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.ai.prompt_registry_dsl import (
            PromptGetProcessor,
        )
        p = PromptGetProcessor(name="osint_report", to="body.prompt")
        assert p.prompt_name == "osint_report"
        assert p.target == "body.prompt"

    @pytest.mark.asyncio
    async def test_get_returns_template_text(self) -> None:
        from src.backend.dsl.engine.processors.ai.prompt_registry_dsl import (
            PromptGetProcessor,
        )
        p = PromptGetProcessor(name="test_prompt", to="body.prompt")
        ex = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Real PromptRegistry.get is async and returns a PromptVersion-like
        # object with .compiled attribute. Mock MUST reflect both.
        mock_version = MagicMock()
        mock_version.compiled = "template content here"
        mock_registry = MagicMock()
        mock_registry.get = AsyncMock(return_value=mock_version)
        with patch(
            "src.backend.services.ai.prompt_registry.get_prompt_registry",
            return_value=mock_registry,
        ):
            await p.process(ex, ctx)
        assert ex.in_message.body.get("prompt") == "template content here"
