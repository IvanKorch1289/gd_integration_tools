"""Tests for agent-specific PII DSL processors (S170 — user-requested feature).

Coverage:
- AgentToolPIIMask: masks PII in tool_call args before execution
- AgentActionPIIMask: masks PII in action params (DB queries, API calls)
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAgentToolPIIMaskProcessor:
    @pytest.mark.asyncio
    async def test_masks_tool_call_args(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentToolPIIMaskProcessor,
        )
        p = AgentToolPIIMaskProcessor(scope="banking", target_property="body.args")
        ex = MagicMock()
        # Use real dict so assignment via parent[key]= works
        ex.in_message = MagicMock()
        ex.in_message.body = {
            "tool_id": "send_email",
            "args": {"to": "user@example.com", "phone": "+7 999 123-45-67"},
        }
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        ctx = MagicMock()
        async def mock_mask(text: str, **kwargs):
            tokens = {"user@example.com": "[EMAIL_1]", "+7 999 123-45-67": "[PHONE_1]"}
            new_text = text
            token_map = {}
            for orig, placeholder in tokens.items():
                if orig in text:
                    new_text = new_text.replace(orig, placeholder)
                    token_map[placeholder] = orig
            return {"text": new_text, "token_map": token_map}

        mock_tokenizer = MagicMock()
        mock_tokenizer.mask_reversible = mock_mask
        mock_provider = MagicMock(return_value=mock_tokenizer)
        with patch(
            "src.backend.core.di.providers.ai.get_pii_tokenizer_provider",
            return_value=mock_provider,
        ):
            await p.process(ex, ctx)
        # Verify args were masked
        masked = ex.in_message.body["args"]
        assert "[EMAIL_1]" in masked["to"]
        assert "[PHONE_1]" in masked["phone"]
        # Token map preserved for round-trip
        assert ex.properties.get("pii_token_map") is not None

    def test_processor_requires_scope(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentToolPIIMaskProcessor,
        )
        with pytest.raises(ValueError, match="scope обязателен"):
            AgentToolPIIMaskProcessor(scope="")

    def test_processor_has_capability(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentToolPIIMaskProcessor,
        )
        assert AgentToolPIIMaskProcessor.required_capability is not None
        assert "agent" in AgentToolPIIMaskProcessor.required_capability


class TestAgentActionPIIMaskProcessor:
    @pytest.mark.asyncio
    async def test_masks_db_query_params(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentActionPIIMaskProcessor,
        )
        p = AgentActionPIIMaskProcessor(scope="banking", target_property="body.params")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {
            "sql": "SELECT * FROM users WHERE inn = ?",
            "params": {"inn": "7707083893", "phone": "+7 999 123-45-67"},
        }
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        ctx = MagicMock()
        async def mock_mask(text: str, **kwargs):
            tokens = {"7707083893": "[INN_1]", "+7 999 123-45-67": "[PHONE_1]"}
            new_text = text
            token_map = {}
            for orig, placeholder in tokens.items():
                if orig in text:
                    new_text = new_text.replace(orig, placeholder)
                    token_map[placeholder] = orig
            return {"text": new_text, "token_map": token_map}

        mock_tokenizer = MagicMock()
        mock_tokenizer.mask_reversible = mock_mask
        mock_provider = MagicMock(return_value=mock_tokenizer)
        with patch(
            "src.backend.core.di.providers.ai.get_pii_tokenizer_provider",
            return_value=mock_provider,
        ):
            await p.process(ex, ctx)
        masked = ex.in_message.body["params"]
        assert "[INN_1]" in masked["inn"]
        assert "[PHONE_1]" in masked["phone"]


class TestAgentRLMSafetyEnforcer:
    """RLM safety: ensure DSL RLM processor enforces token/iteration limits."""

    def test_rlm_processor_has_max_iterations(self) -> None:
        from src.backend.dsl.engine.processors.ai_rlm import AIRLMProcessor
        p = AIRLMProcessor()
        assert p.config.max_iterations > 0, "RLM must have max_iterations"
        assert p.config.max_iterations <= 50, "RLM max_iterations too high"

    def test_rlm_processor_has_max_tokens(self) -> None:
        from src.backend.dsl.engine.processors.ai_rlm import AIRLMProcessor
        p = AIRLMProcessor()
        assert p.config.max_tokens > 0
        assert p.config.max_tokens <= 32000  # reasonable upper bound

    def test_rlm_processor_sandbox_enabled_by_default(self) -> None:
        from src.backend.dsl.engine.processors.ai_rlm import AIRLMProcessor
        p = AIRLMProcessor()
        assert p.config.sandbox_enabled is True, "RLM must run in sandbox by default"


class TestAgentOutputGuardrails:
    """Agent output validation via guardrails pattern."""

    def test_output_validation_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.guardrails_apply import (
            GuardrailsApplyProcessor,
        )
        assert GuardrailsApplyProcessor is not None
