"""Unit tests for AIRequest / AIResponse dataclasses.

Covers: construction, defaults, immutability.
"""

from __future__ import annotations

import pytest

from src.backend.core.ai.gateway_models import AIRequest, AIResponse


class TestAIRequest:
    """Tests for :class:`AIRequest`."""

    def test_minimal_construction(self) -> None:
        """Only required fields are workflow_id, tenant_id, correlation_id."""
        req = AIRequest(workflow_id="wf1", tenant_id="t1", correlation_id="c1")
        assert req.workflow_id == "wf1"
        assert req.tenant_id == "t1"
        assert req.correlation_id == "c1"
        assert req.prompt_ref is None
        assert req.prompt_inline is None
        assert req.context == {}
        assert req.stream is False

    def test_full_construction(self) -> None:
        """All fields populated."""
        req = AIRequest(
            workflow_id="wf2",
            tenant_id="t2",
            correlation_id="c2",
            prompt_ref="ref1",
            prompt_inline="hello",
            context={"k": "v"},
            stream=True,
        )
        assert req.prompt_ref == "ref1"
        assert req.prompt_inline == "hello"
        assert req.context == {"k": "v"}
        assert req.stream is True

    def test_frozen_raises_on_setattr(self) -> None:
        """slots + frozen dataclass should reject mutation."""
        req = AIRequest(workflow_id="w", tenant_id="t", correlation_id="c")
        with pytest.raises(AttributeError):
            req.workflow_id = "x"  # type: ignore[misc]


class TestAIResponse:
    """Tests for :class:`AIResponse`."""

    def test_minimal_construction(self) -> None:
        """Only content is required."""
        resp = AIResponse(content="hi")
        assert resp.content == "hi"
        assert resp.structured is None
        assert resp.tokens_prompt == 0
        assert resp.tokens_completion == 0
        assert resp.cost_usd == 0.0
        assert resp.model_used == ""
        assert resp.pii_detected is False
        assert resp.guardrails_verdict == {}

    def test_full_construction(self) -> None:
        """All fields populated."""
        resp = AIResponse(
            content="hello",
            structured={"a": 1},
            tokens_prompt=10,
            tokens_completion=5,
            cost_usd=0.0001,
            model_used="gpt-4",
            pii_detected=True,
            guardrails_verdict={"input": "safe", "output": "warn"},
        )
        assert resp.structured == {"a": 1}
        assert resp.tokens_prompt == 10
        assert resp.tokens_completion == 5
        assert resp.cost_usd == 0.0001
        assert resp.model_used == "gpt-4"
        assert resp.pii_detected is True
        assert resp.guardrails_verdict == {"input": "safe", "output": "warn"}

    def test_frozen_raises_on_setattr(self) -> None:
        """slots + frozen dataclass should reject mutation."""
        resp = AIResponse(content="x")
        with pytest.raises(AttributeError):
            resp.content = "y"  # type: ignore[misc]
