"""Coverage tests для sanitize_mixin (Sprint 222, 2026-08-17).

TDD: tests для core/ai/policy/enforcer/sanitize_mixin.py.

sanitize_mixin.py coverage baseline: 18% (per Sprint 221 analysis).
Target: 60-70% via these tests.

Coverage targets:
- sanitize_input: empty prompt, no tokenizer, normal sanitize,
  tokenizer exception (fail-soft)
- sanitize_output: empty content, no tokenizer, normal sanitize,
  sanitizer exception, pii_detected=True when replacements present
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.ai.gateway import AIRequest, AIResponse
from src.backend.core.ai.policy.enforcer.sanitize_mixin import SanitizeMixin


class _StubEnforcer(SanitizeMixin):
    """Minimal subclass to test mixin methods in isolation."""

    def __init__(self) -> None:
        self._pii_tokenizer: MagicMock | None = None


@pytest.fixture
def enforcer() -> _StubEnforcer:
    return _StubEnforcer()


@pytest.fixture
def policy() -> MagicMock:
    p = MagicMock()
    p.language = "ru"
    return p


def _make_request(prompt_inline: str | None = None, prompt_ref: str | None = None) -> AIRequest:
    """Helper: AIRequest requires workflow_id, tenant_id, correlation_id."""
    return AIRequest(
        workflow_id="test_wf",
        tenant_id="test_tenant",
        correlation_id="test_corr",
        prompt_inline=prompt_inline,
        prompt_ref=prompt_ref,
    )


class TestSanitizeInputEmpty:
    """Edge cases: empty prompt, no tokenizer."""

    @pytest.mark.asyncio
    async def test_empty_prompt_returns_empty_string(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        request = _make_request(prompt_inline="")
        result = await enforcer.sanitize_input(request, policy)
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_tokenizer_returns_prompt_unchanged(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        """Если _pii_tokenizer is None → prompt возвращается без изменений."""
        enforcer._pii_tokenizer = None
        request = _make_request(prompt_inline="user@example.com text")
        result = await enforcer.sanitize_input(request, policy)
        assert result == "user@example.com text"

    @pytest.mark.asyncio
    async def test_prompt_with_only_prompt_ref(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        """AIRequest с prompt_ref (вместо prompt_inline) — также работает."""
        request = _make_request(prompt_ref="reference prompt", prompt_inline=None)
        enforcer._pii_tokenizer = None
        result = await enforcer.sanitize_input(request, policy)
        assert result == "reference prompt"


class TestSanitizeInputNormal:
    """Normal sanitize path."""

    @pytest.mark.asyncio
    async def test_normal_sanitize_replaces_pii(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        """Нормальный PII → sanitized_text из tokenizer."""

        mock_result = MagicMock()
        mock_result.sanitized_text = "[REDACTED] user text"
        mock_tokenizer = AsyncMock(return_value=mock_result)
        mock_pii_tokenizer = MagicMock()
        mock_pii_tokenizer.sanitize_async = mock_tokenizer
        enforcer._pii_tokenizer = mock_pii_tokenizer

        request = _make_request(prompt_inline="user@example.com text")
        result = await enforcer.sanitize_input(request, policy)
        assert result == "[REDACTED] user text"
        mock_tokenizer.assert_awaited_once_with(
            "user@example.com text", language="ru",
        )


class TestSanitizeInputException:
    """Tokenizer exception handling (P0-S5)."""

    @pytest.mark.asyncio
    async def test_tokenizer_exception_fails_closed_in_production(
        self, enforcer: _StubEnforcer, policy: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """P0-S5: tokenizer throws в production → propagate exception (fail-closed)."""
        mock_tokenizer = AsyncMock(side_effect=RuntimeError("PII service down"))
        mock_pii_tokenizer = MagicMock()
        mock_pii_tokenizer.sanitize_async = mock_tokenizer
        enforcer._pii_tokenizer = mock_pii_tokenizer

        request = _make_request(prompt_inline="user@example.com text")

        # P0-S5: production (ai_policy_enforce=True) → fail-closed (raise).
        monkeypatch.setattr(
            "src.backend.core.config.features.feature_flags.ai_policy_enforce",
            True,
            raising=False,
        )
        with pytest.raises(RuntimeError, match="PII service down"):
            await enforcer.sanitize_input(request, policy)

    @pytest.mark.asyncio
    async def test_tokenizer_exception_failsoft_in_dev(
        self, enforcer: _StubEnforcer, policy: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """P0-S5: dev (ai_policy_enforce=False) → fail-soft (return original)."""
        mock_tokenizer = AsyncMock(side_effect=RuntimeError("PII service down"))
        mock_pii_tokenizer = MagicMock()
        mock_pii_tokenizer.sanitize_async = mock_tokenizer
        enforcer._pii_tokenizer = mock_pii_tokenizer

        request = _make_request(prompt_inline="user@example.com text")

        # dev/staging (ai_policy_enforce=False) → backward compat fail-soft.
        monkeypatch.setattr(
            "src.backend.core.config.features.feature_flags.ai_policy_enforce",
            False,
            raising=False,
        )
        result = await enforcer.sanitize_input(request, policy)
        assert result == "user@example.com text"


class TestSanitizeOutputEmpty:
    """Edge cases: empty content, no tokenizer."""

    @pytest.mark.asyncio
    async def test_empty_content_returns_response_unchanged(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        response = AIResponse(content="", model_used="test")
        result = await enforcer.sanitize_output(response, policy)
        assert result is response

    @pytest.mark.asyncio
    async def test_no_tokenizer_returns_response_unchanged(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        enforcer._pii_tokenizer = None
        response = AIResponse(content="LLM response text", model_used="test")
        result = await enforcer.sanitize_output(response, policy)
        assert result is response


class TestSanitizeOutputNormal:
    """Normal sanitize path with PII detection."""

    @pytest.mark.asyncio
    async def test_normal_sanitize_replaces_pii_in_response(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        """Normal path: PII → masked text + pii_detected=True."""

        mock_result = MagicMock()
        mock_result.sanitized_text = "[REDACTED] response"
        mock_result.replacements = ["email@example.com"]  # non-empty → pii_detected=True
        mock_tokenizer = AsyncMock(return_value=mock_result)
        mock_pii_tokenizer = MagicMock()
        mock_pii_tokenizer.sanitize_async = mock_tokenizer
        enforcer._pii_tokenizer = mock_pii_tokenizer

        response = AIResponse(
            content="Contact email@example.com for details",
            model_used="gpt-4",
            tokens_prompt=10,
            tokens_completion=20,
            cost_usd=0.001,
        )
        result = await enforcer.sanitize_output(response, policy)

        assert result.content == "[REDACTED] response"
        assert result.pii_detected is True
        assert result.model_used == "gpt-4"
        assert result.tokens_prompt == 10
        assert result.tokens_completion == 20
        assert result.cost_usd == 0.001

    @pytest.mark.asyncio
    async def test_no_pii_detected_when_no_replacements(
        self, enforcer: _StubEnforcer, policy: MagicMock,
    ) -> None:
        """Если replacements пуст → pii_detected=False."""

        mock_result = MagicMock()
        mock_result.sanitized_text = "Clean text"
        mock_result.replacements = []  # empty → pii_detected=False
        mock_tokenizer = AsyncMock(return_value=mock_result)
        mock_pii_tokenizer = MagicMock()
        mock_pii_tokenizer.sanitize_async = mock_tokenizer
        enforcer._pii_tokenizer = mock_pii_tokenizer

        response = AIResponse(content="Clean text", model_used="test")
        result = await enforcer.sanitize_output(response, policy)

        assert result.content == "Clean text"
        assert result.pii_detected is False


class TestSanitizeOutputException:
    """Tokenizer exception handling (P0-S5)."""

    @pytest.mark.asyncio
    async def test_tokenizer_exception_fails_closed_in_production(
        self, enforcer: _StubEnforcer, policy: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """P0-S5: production → propagate exception (fail-closed)."""
        mock_tokenizer = AsyncMock(side_effect=RuntimeError("service down"))
        mock_pii_tokenizer = MagicMock()
        mock_pii_tokenizer.sanitize_async = mock_tokenizer
        enforcer._pii_tokenizer = mock_pii_tokenizer

        response = AIResponse(
            content="Contains PII",
            model_used="test",
            guardrails_verdict={"flagged": True},
        )

        monkeypatch.setattr(
            "src.backend.core.config.features.feature_flags.ai_policy_enforce",
            True,
            raising=False,
        )
        with pytest.raises(RuntimeError, match="service down"):
            await enforcer.sanitize_output(response, policy)

    @pytest.mark.asyncio
    async def test_tokenizer_exception_failsoft_in_dev(
        self, enforcer: _StubEnforcer, policy: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """P0-S5: dev → fail-soft (return original)."""
        mock_tokenizer = AsyncMock(side_effect=RuntimeError("service down"))
        mock_pii_tokenizer = MagicMock()
        mock_pii_tokenizer.sanitize_async = mock_tokenizer
        enforcer._pii_tokenizer = mock_pii_tokenizer

        response = AIResponse(
            content="Contains PII",
            model_used="test",
            guardrails_verdict={"flagged": True},
        )

        monkeypatch.setattr(
            "src.backend.core.config.features.feature_flags.ai_policy_enforce",
            False,
            raising=False,
        )
        result = await enforcer.sanitize_output(response, policy)
        assert result is response
        assert result.content == "Contains PII"
        assert result.guardrails_verdict == {"flagged": True}
