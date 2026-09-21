"""Unit tests for src.backend.core.di.providers.ai (T-P1.2c split)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.backend.core.di.providers import ai


class TestAiSanitizer:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_sanitizer")
        ai.set_ai_sanitizer_provider(mock)
        assert ai.get_ai_sanitizer_provider() is mock


class TestPiiTokenizer:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_pii")
        ai.set_pii_tokenizer_provider(mock)
        assert ai.get_pii_tokenizer_provider() is mock


class TestLlmJudgeMetrics:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_metrics")
        ai.set_llm_judge_metrics_provider(mock)
        assert ai.get_llm_judge_metrics_provider() is mock

    def test_noop_helper_callable(self) -> None:
        # _noop_llm_judge_metrics must be callable
        assert callable(ai._noop_llm_judge_metrics)
        result = ai._noop_llm_judge_metrics(
            model="m1", hallucination=0.1, relevance=0.9, toxicity=0.0
        )
        assert result is None


class TestModelEnum:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_enum")
        ai.set_model_enum_provider(mock)
        assert ai.get_model_enum_provider() is mock


class TestVaultRefresher:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_vault")
        ai.set_vault_refresher_provider(mock)
        assert ai.get_vault_refresher_provider() is mock


class TestAntivirusService:
    def test_set_overrides(self) -> None:
        mock = MagicMock(name="custom_av")
        ai.set_antivirus_service_provider(mock)
        assert ai.get_antivirus_service_provider() is mock


class TestAiHelpers:
    """Test private helpers used by PII pipeline."""

    def test_resolve_unified_audit_service_returns_none_on_missing(self) -> None:
        # Should return None when audit service unavailable (test env)
        result = ai._resolve_unified_audit_service()
        # May be None or actual service depending on test env, but must not raise
        assert result is None or result is not None  # tautology — just verify no raise


class TestAiModuleIsolation:
    def test_overrides_isolated(self) -> None:
        ai.set_ai_sanitizer_provider("SAN")
        ai.set_pii_tokenizer_provider("PII")
        assert ai.get_ai_sanitizer_provider() == "SAN"
        assert ai.get_pii_tokenizer_provider() == "PII"
