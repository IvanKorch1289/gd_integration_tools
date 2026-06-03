"""Integration-тесты LangfusePIICallback (S24 W1, ADR-NEW-16).

Проверяют, что Langfuse before_send hook anonymizes PII в payload до
отправки в API. Тесты используют только in-memory подмену
``get_ai_sanitizer_provider`` (без реального Langfuse SDK) — нас интересует
именно поведение callback'а, а не SDK-обёртка.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest


@dataclass(slots=True)
class _StubSanitizationResult:
    """Минимальный stub под SanitizationResult API."""

    sanitized_text: str
    replacements: dict[str, str]


class _StubSanitizer:
    """In-memory sanitizer: подменяет цифры на [REDACTED]."""

    def sanitize_text(self, text: str) -> _StubSanitizationResult:
        import re

        cleaned = re.sub(r"\d{3,}", "[REDACTED]", text)
        replacements = {"[REDACTED]": "***"} if cleaned != text else {}
        return _StubSanitizationResult(sanitized_text=cleaned, replacements=replacements)


def test_callback_is_no_op_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """При PRESIDIO_PII_ENABLED=False callback не модифицирует payload."""
    from src.backend.core.config import features
    from src.backend.services.ai.gateway.langfuse_pii_callback import (
        LangfusePIICallback,
    )

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", False, raising=True
    )
    cb = LangfusePIICallback()
    event = {
        "input": "ИНН 7707083893",
        "output": {"text": "Ответ"},
        "metadata": {"user": "Иванов"},
    }
    result = cb(event)
    assert result["input"] == "ИНН 7707083893"
    assert result["output"]["text"] == "Ответ"


def test_callback_anonymizes_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """При PRESIDIO_PII_ENABLED=True callback заменяет цифры через stub."""
    from src.backend.core.config import features
    from src.backend.core.di import providers
    from src.backend.services.ai.gateway.langfuse_pii_callback import (
        LangfusePIICallback,
    )

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", True, raising=True
    )
    providers.set_ai_sanitizer_provider(_StubSanitizer())
    try:
        cb = LangfusePIICallback(tenant_id="tenant-123")
        event = {
            "input": "ИНН 7707083893",
            "output": {"text": "Номер договора 999888"},
            "metadata": {"user": "Иванов И.И."},
        }
        result = cb(event)
        assert "[REDACTED]" in result["input"]
        assert "[REDACTED]" in result["output"]["text"]
    finally:
        providers.ai._overrides.pop("ai_sanitizer", None)


def test_anonymize_trace_payload_walks_nested(monkeypatch: pytest.MonkeyPatch) -> None:
    """anonymize_trace_payload рекурсивно обрабатывает list/dict/str."""
    from src.backend.core.config import features
    from src.backend.core.di import providers
    from src.backend.services.ai.gateway.langfuse_pii_callback import (
        anonymize_trace_payload,
    )

    monkeypatch.setattr(
        features.feature_flags, "presidio_pii_enabled", True, raising=True
    )
    providers.set_ai_sanitizer_provider(_StubSanitizer())
    try:
        payload = {
            "messages": [
                {"role": "user", "content": "Кредитное дело 12345"},
                {"role": "assistant", "content": "OK"},
            ],
            "tenant": "acme",
            "amount": 12345,
        }
        result = anonymize_trace_payload(payload, tenant_id="acme")
        assert "[REDACTED]" in result["messages"][0]["content"]
        assert result["messages"][1]["content"] == "OK"
        assert result["tenant"] == "acme"  # короткие строки без цифр не меняются
        assert result["amount"] == 12345  # не строка → не обрабатывается
    finally:
        providers.ai._overrides.pop("ai_sanitizer", None)


def test_anonymize_passthrough_on_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """anonymize_trace_payload(None) → None passthrough."""
    from src.backend.services.ai.gateway.langfuse_pii_callback import (
        anonymize_trace_payload,
    )

    assert anonymize_trace_payload(None) is None
