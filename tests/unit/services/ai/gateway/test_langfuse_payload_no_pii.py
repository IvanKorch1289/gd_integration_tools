"""Unit test для Block 1.2 (gap-ai-1.2, ADR-0072).

Проверяет что LangFuseCallbackV3 (v3) не отправляет сырые PII в Langfuse:

1. При ``LangFuseSettings.sanitize_traces=True`` + ``PRESIDIO_PII_ENABLED=True``
   ``input``/``output``/``metadata`` проходят через
   ``anonymize_trace_payload`` (DI-resolved sanitizer) до вызова Langfuse API.
2. При ``sanitize_traces=False`` — passthrough.
3. При ``PRESIDIO_PII_ENABLED=False`` — passthrough (single source of truth
   через feature_flag, даже если sanitize_traces=True).

W11 GAP-AI: v2 удалён, тесты обновлены на v3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest


@dataclass(slots=True)
class _StubSanitizationResult:
    """Stub под :class:`SanitizationResult`."""

    sanitized_text: str
    replacements: dict[str, str]


class _StubSanitizer:
    """In-memory sanitizer: маскирует цифры 3+ как [REDACTED]."""

    def sanitize_text(self, text: str) -> _StubSanitizationResult:
        import re

        cleaned = re.sub(r"\d{3,}", "[REDACTED]", text)
        return _StubSanitizationResult(
            sanitized_text=cleaned,
            replacements={"[REDACTED]": "***"} if cleaned != text else {},
        )


@pytest.fixture()
def stub_langfuse_v3_client() -> MagicMock:
    """Stub Langfuse v3 client с capturing span.update()."""
    fake_span = MagicMock()
    fake_span.__enter__ = MagicMock(return_value=fake_span)
    fake_span.__exit__ = MagicMock(return_value=False)

    fake_client = MagicMock()
    fake_client.start_as_current_span.return_value = fake_span

    return fake_client


class TestLangFuseV3Anonymization:
    """PII anonymization tests for LangFuseCallbackV3."""

    async def test_callback_v3_anonymizes_when_flag_on(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_langfuse_v3_client: MagicMock,
    ) -> None:
        """LangFuseCallbackV3 маскирует input/output при sanitize_traces=True."""
        from src.backend.core.config import ai_2026, features
        from src.backend.core.di import providers
        from src.backend.services.ai.gateway.langfuse_callback_v3 import (
            LangFuseCallbackV3,
        )

        monkeypatch.setattr(
            features.feature_flags, "presidio_pii_enabled", True, raising=True
        )
        monkeypatch.setattr(
            ai_2026.langfuse_settings, "enabled", True, raising=True
        )
        monkeypatch.setattr(
            ai_2026.langfuse_settings, "sanitize_traces", True, raising=True
        )
        providers.set_ai_sanitizer_provider(_StubSanitizer())
        try:
            cb = LangFuseCallbackV3()
            cb._lf = stub_langfuse_v3_client
            cb._inited = True

            kwargs = {
                "model": "openai/gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": "ИНН 7707083893, договор №12345"},
                ],
                "metadata": {"tenant": "bank-msk", "route": "credit_check"},
            }
            response = MagicMock()
            response.choices = [
                MagicMock(message=MagicMock(content="Клиент Иванов 9998887"))
            ]
            response.usage = None
            response.response_cost = 0.001
            cb(kwargs, response)

            # Verify anonymized messages were passed to start_as_current_span (input kwarg).
            # output/metadata go to span.update — check both.
            stub_langfuse_v3_client.start_as_current_span.assert_called_once()
            fake_span = stub_langfuse_v3_client.start_as_current_span.return_value.__enter__.return_value
            span_kwargs = stub_langfuse_v3_client.start_as_current_span.call_args.kwargs
            captured_input = span_kwargs.get("input")
            captured_metadata = fake_span.update.call_args.kwargs.get("metadata")

            assert captured_input is not None
            assert "7707083893" not in str(captured_input)
            assert "12345" not in str(captured_input)
            assert captured_metadata is not None
            # output is anonymized too
            update_kwargs = fake_span.update.call_args.kwargs
            assert "9998887" not in str(update_kwargs.get("output"))
        finally:
            providers.ai._overrides.pop("ai_sanitizer", None)

    async def test_callback_v3_passthrough_when_sanitize_traces_off(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_langfuse_v3_client: MagicMock,
    ) -> None:
        """При sanitize_traces=False payload проходит без анонимизации."""
        from src.backend.core.config import ai_2026, features
        from src.backend.core.di import providers
        from src.backend.services.ai.gateway.langfuse_callback_v3 import (
            LangFuseCallbackV3,
        )

        monkeypatch.setattr(
            features.feature_flags, "presidio_pii_enabled", True, raising=True
        )
        monkeypatch.setattr(
            ai_2026.langfuse_settings, "enabled", True, raising=True
        )
        monkeypatch.setattr(
            ai_2026.langfuse_settings, "sanitize_traces", False, raising=True
        )
        providers.set_ai_sanitizer_provider(_StubSanitizer())
        try:
            cb = LangFuseCallbackV3()
            cb._lf = stub_langfuse_v3_client
            cb._inited = True

            kwargs = {
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "ИНН 7707083893"}],
            }
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="ok 12345"))]
            response.usage = None
            response.response_cost = 0.0
            cb(kwargs, response)

            stub_langfuse_v3_client.start_as_current_span.assert_called_once()
            span_kwargs = stub_langfuse_v3_client.start_as_current_span.call_args.kwargs
            captured_input = span_kwargs.get("input")
            # Passthrough — цифры остались.
            assert "7707083893" in str(captured_input)
        finally:
            providers.ai._overrides.pop("ai_sanitizer", None)

    async def test_callback_v3_passthrough_when_presidio_off(
        self,
        monkeypatch: pytest.MonkeyPatch,
        stub_langfuse_v3_client: MagicMock,
    ) -> None:
        """При PRESIDIO_PII_ENABLED=False payload не анонимизируется (single source)."""
        from src.backend.core.config import ai_2026, features
        from src.backend.core.di import providers
        from src.backend.services.ai.gateway.langfuse_callback_v3 import (
            LangFuseCallbackV3,
        )

        monkeypatch.setattr(
            features.feature_flags, "presidio_pii_enabled", False, raising=True
        )
        monkeypatch.setattr(
            ai_2026.langfuse_settings, "enabled", True, raising=True
        )
        monkeypatch.setattr(
            ai_2026.langfuse_settings, "sanitize_traces", True, raising=True
        )
        providers.set_ai_sanitizer_provider(_StubSanitizer())
        try:
            cb = LangFuseCallbackV3()
            cb._lf = stub_langfuse_v3_client
            cb._inited = True

            kwargs = {
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": "ИНН 7707083893"}],
            }
            response = MagicMock()
            response.choices = [MagicMock(message=MagicMock(content="ok 12345"))]
            response.usage = None
            response.response_cost = 0.0
            cb(kwargs, response)

            stub_langfuse_v3_client.start_as_current_span.assert_called_once()
            span_kwargs = stub_langfuse_v3_client.start_as_current_span.call_args.kwargs
            captured_input = span_kwargs.get("input")
            # PRESIDIO_PII_ENABLED=False → anonymize_trace_payload — no-op.
            assert "7707083893" in str(captured_input)
        finally:
            providers.ai._overrides.pop("ai_sanitizer", None)
