"""Sprint 30 (B): tests for src/backend/services/ai/guardrails/lakera_client.py.

Lakera is the PII/guardrail provider. Construction without API key
must fail-closed (P0-S2 audit fix).
"""
from __future__ import annotations

import pytest


class TestLakeraClientFailClosed:
    """Lakera client должен fail-closed без LAKERA_API_KEY (P0-S2)."""

    def test_no_api_key_raises_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Sprint 7 P0-S2: construction without API key → raises LakeraGuardrailUnavailableError."""
        monkeypatch.delenv("LAKERA_API_KEY", raising=False)

        from src.backend.services.ai.guardrails.lakera_client import (
            LakeraClient,
            LakeraGuardrailUnavailableError,
        )

        with pytest.raises(LakeraGuardrailUnavailableError, match="LAKERA_API_KEY"):
            LakeraClient()

    def test_empty_api_key_raises_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Empty string API key also fails closed (no whitespace bypass)."""
        monkeypatch.setenv("LAKERA_API_KEY", "")

        from src.backend.services.ai.guardrails.lakera_client import (
            LakeraClient,
            LakeraGuardrailUnavailableError,
        )

        with pytest.raises(LakeraGuardrailUnavailableError):
            LakeraClient()


class TestLakeraClientAvailable:
    """When LAKERA_API_KEY is set, client should construct successfully."""

    def test_with_api_key_constructs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LAKERA_API_KEY", "test-key-12345")

        from src.backend.services.ai.guardrails.lakera_client import LakeraClient

        client = LakeraClient()
        assert client is not None
        # Should store the API key (or hash, depending on implementation)
        # Just verify no exception
        assert hasattr(client, "screen")
