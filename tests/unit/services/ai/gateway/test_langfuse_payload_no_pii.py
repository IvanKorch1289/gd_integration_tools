"""Unit test для Block 1.2 (gap-ai-1.2, ADR-0072).

Проверяет что LangFuseCostCallback (v2) и LangFuseCallbackV3 не отправляют
сырые PII в Langfuse:

1. При ``LangFuseSettings.sanitize_traces=True`` + ``PRESIDIO_PII_ENABLED=True``
   ``input``/``output``/``metadata`` проходят через
   ``anonymize_trace_payload`` (DI-resolved sanitizer) до вызова Langfuse API.
2. При ``sanitize_traces=False`` — passthrough.
3. При ``PRESIDIO_PII_ENABLED=False`` — passthrough (single source of truth
   через feature_flag, даже если sanitize_traces=True).
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
def stub_langfuse_client(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub Langfuse client с capturing generation()."""
    captured: dict[str, Any] = {}

    class _FakeGeneration:
        def __call__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class _FakeTrace:
        generation = _FakeGeneration()

    class _FakeLangfuse:
        def __init__(self, **_: Any) -> None:
            pass

        def trace(self, **_: Any) -> _FakeTrace:
            return _FakeTrace()

    import sys
    from types import ModuleType

    fake_mod = ModuleType("langfuse")
    fake_mod.Langfuse = _FakeLangfuse  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langfuse", fake_mod)
    return captured


def test_callback_v2_anonymizes_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, stub_langfuse_client: dict[str, Any]
) -> None:
    """LangFuseCostCallback маскирует input/output при sanitize_traces=True."""
    from src.backend.core.config import ai_2026, features
    from src.backend.core.di import providers
    from src.backend.services.ai.gateway.langfuse_callback import LangFuseCostCallback

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
        cb = LangFuseCostCallback()
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

        captured_input = stub_langfuse_client.get("input")
        captured_output = stub_langfuse_client.get("output")
        assert captured_input is not None
        assert "7707083893" not in str(captured_input)
        assert "12345" not in str(captured_input)
        assert captured_output is not None
        assert "9998887" not in str(captured_output)
    finally:
        providers._overrides.pop("ai_sanitizer", None)


def test_callback_v2_passthrough_when_sanitize_traces_off(
    monkeypatch: pytest.MonkeyPatch, stub_langfuse_client: dict[str, Any]
) -> None:
    """При sanitize_traces=False payload проходит без анонимизации."""
    from src.backend.core.config import ai_2026, features
    from src.backend.core.di import providers
    from src.backend.services.ai.gateway.langfuse_callback import LangFuseCostCallback

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
        cb = LangFuseCostCallback()
        kwargs = {
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "ИНН 7707083893"}],
        }
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="ok 12345"))]
        response.usage = None
        response.response_cost = 0.0
        cb(kwargs, response)

        captured_input = stub_langfuse_client.get("input")
        # Passthrough — цифры остались.
        assert "7707083893" in str(captured_input)
    finally:
        providers._overrides.pop("ai_sanitizer", None)


def test_callback_v2_passthrough_when_presidio_off(
    monkeypatch: pytest.MonkeyPatch, stub_langfuse_client: dict[str, Any]
) -> None:
    """При PRESIDIO_PII_ENABLED=False payload не анонимизируется (single source)."""
    from src.backend.core.config import ai_2026, features
    from src.backend.core.di import providers
    from src.backend.services.ai.gateway.langfuse_callback import LangFuseCostCallback

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
        cb = LangFuseCostCallback()
        kwargs = {
            "model": "openai/gpt-4o-mini",
            "messages": [{"role": "user", "content": "ИНН 7707083893"}],
        }
        response = MagicMock()
        response.choices = [MagicMock(message=MagicMock(content="ok 12345"))]
        response.usage = None
        response.response_cost = 0.0
        cb(kwargs, response)

        captured_input = stub_langfuse_client.get("input")
        # PRESIDIO_PII_ENABLED=False → anonymize_trace_payload — no-op.
        assert "7707083893" in str(captured_input)
    finally:
        providers._overrides.pop("ai_sanitizer", None)
