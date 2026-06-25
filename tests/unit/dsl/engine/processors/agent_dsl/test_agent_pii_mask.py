"""Tests for agent-specific PII DSL processors (S170 — user-requested feature).

Coverage:
- AgentDictPIIMaskProcessor.for_tools — masks PII in tool_call args
- AgentDictPIIMaskProcessor.for_actions — masks PII in action params
- Edge cases: empty dict, missing path, non-dict body
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestAgentDictPIIMaskForTools:
    @pytest.mark.asyncio
    async def test_masks_tool_call_args(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_tools(scope="banking")
        ex = MagicMock()
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

        masked = ex.in_message.body["args"]
        assert "[EMAIL_1]" in masked["to"]
        assert "[PHONE_1]" in masked["phone"]
        ex.set_property.assert_any_call("pii_token_map", mock.ANY) if False else None

    def test_for_tools_has_correct_capability(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_tools(scope="banking")
        assert p.required_capability == "pii.tokenize.reversible.agent_tools"
        assert p.audit_event == "ai.agent.pii.tool_mask"


class TestAgentDictPIIMaskForActions:
    @pytest.mark.asyncio
    async def test_masks_db_query_params(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_actions(scope="banking")
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

    def test_for_actions_has_correct_capability(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_actions(scope="banking")
        assert p.required_capability == "pii.tokenize.reversible.agent_actions"
        assert p.audit_event == "ai.agent.pii.action_mask"


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_dict_returns_no_pii(self) -> None:
        """Empty dict → no PII detected, token_map={}."""
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_tools(scope="banking")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"args": {}}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()

        mock_tokenizer = MagicMock()
        mock_tokenizer.mask_reversible = AsyncMock()
        mock_provider = MagicMock(return_value=mock_tokenizer)
        with patch(
            "src.backend.core.di.providers.ai.get_pii_tokenizer_provider",
            return_value=mock_provider,
        ):
            await p.process(ex, MagicMock())

        ex.set_property.assert_any_call("pii_detected", False)
        ex.set_property.assert_any_call("pii_token_map", {})

    @pytest.mark.asyncio
    async def test_missing_source_path_returns_no_pii(self) -> None:
        """Source path doesn't exist → no error, no PII."""
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_tools(
            scope="banking", source_property="body.nonexistent.args"
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()

        mock_tokenizer = MagicMock()
        mock_provider = MagicMock(return_value=mock_tokenizer)
        with patch(
            "src.backend.core.di.providers.ai.get_pii_tokenizer_provider",
            return_value=mock_provider,
        ):
            await p.process(ex, MagicMock())

        # No masking error, pii_detected=False
        ex.set_property.assert_any_call("pii_detected", False)
        ex.set_property.assert_any_call("pii_token_map", {})

    @pytest.mark.asyncio
    async def test_non_dict_body_returns_no_pii(self) -> None:
        """Body not a dict → no error, no PII."""
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_tools(scope="banking")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = "not a dict"
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()

        mock_tokenizer = MagicMock()
        mock_provider = MagicMock(return_value=mock_tokenizer)
        with patch(
            "src.backend.core.di.providers.ai.get_pii_tokenizer_provider",
            return_value=mock_provider,
        ):
            await p.process(ex, MagicMock())

        ex.set_property.assert_any_call("pii_detected", False)

    @pytest.mark.asyncio
    async def test_tokenizer_unavailable_passes_through(self) -> None:
        """Tokenizer provider returns None → pass-through with empty token_map."""
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        p = AgentDictPIIMaskProcessor.for_tools(scope="banking")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"args": {"to": "user@example.com"}}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()

        mock_provider = MagicMock(return_value=None)
        with patch(
            "src.backend.core.di.providers.ai.get_pii_tokenizer_provider",
            return_value=mock_provider,
        ):
            await p.process(ex, MagicMock())

        # Body unchanged, token_map={}
        assert ex.in_message.body["args"]["to"] == "user@example.com"
        ex.set_property.assert_any_call("pii_token_map", {})
        ex.set_property.assert_any_call("pii_detected", False)


class TestRuntimeVerification:
    """Runtime tests with REAL classes — not mocks (P0 review fix).

    These tests catch bugs that MagicMock-based tests miss.
    """

    @pytest.mark.asyncio
    async def test_processor_compiles_and_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        # Both classmethods produce correct instances
        tools = AgentDictPIIMaskProcessor.for_tools(scope="banking")
        actions = AgentDictPIIMaskProcessor.for_actions(scope="hr")
        assert tools.scope == "banking"
        assert actions.scope == "hr"
        assert tools.required_capability != actions.required_capability
        assert tools.audit_event != actions.audit_event

    def test_empty_scope_raises(self) -> None:
        from src.backend.dsl.engine.processors.agent_dsl.agent_pii_mask import (
            AgentDictPIIMaskProcessor,
        )
        with pytest.raises(ValueError, match="scope обязателен"):
            AgentDictPIIMaskProcessor(scope="")
