"""ADR-0401 — fast-path маскирования email применяется ВСЕМИ потребителями.

До фикса fast-path ``sub_email`` (ADR-0392) использовал только
``entrypoints/middlewares/data_masking.py``. Остальные потребители
PII-паттернов вызывали ``EMAIL.sub(...)`` напрямую:

* ``core/security/pii_masker.py`` — generic-цикл по словарю patterns;
* ``infrastructure/observability/pii_filter.py`` — structlog-процессор.

Оба сканировали строку линейно даже при отсутствии ``@`` — то есть
канонический fast-path применялся не во всех местах.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.security import pii_masker, pii_patterns
from src.backend.infrastructure.observability import pii_filter

pytestmark = pytest.mark.unit


class _SpyPattern:
    """Регекс-подмена: считает вызовы ``sub``."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def sub(self, repl: Any, value: str) -> str:  # noqa: ARG002 — spy-заглушка
        self.calls.append(value)
        return "REPLACED"


# ── pii_patterns: fast-path не запускает регекс без ``@`` ────────────────


def test_sub_email_skips_regex_when_no_at_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    """Строка без ``@`` не сканируется регексом вообще."""
    spy = _SpyPattern()
    monkeypatch.setattr(pii_patterns, "EMAIL", spy)

    assert pii_patterns.sub_email("X", "no at sign here") == "no at sign here"
    assert spy.calls == []


def test_sub_email_applies_regex_when_at_sign_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Строка с ``@`` обрабатывается регексом (fast-path не ломает маскирование)."""
    spy = _SpyPattern()
    monkeypatch.setattr(pii_patterns, "EMAIL", spy)

    assert pii_patterns.sub_email("X", "a@b.io") == "REPLACED"
    assert spy.calls == ["a@b.io"]


# ── pii_filter (structlog) использует fast-path ───────────────────────────


def test_pii_filter_uses_sub_email_fastpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """structlog-фильтр обязан звать ``sub_email``, а не ``EMAIL.sub``."""
    calls: list[str] = []

    def _fake_sub_email(repl: Any, value: str) -> str:
        calls.append(value)
        return pii_patterns.sub_email(repl, value)

    monkeypatch.setattr(pii_filter, "sub_email", _fake_sub_email, raising=False)

    out = pii_filter.redact_for_observability("user@example.com")

    assert calls == ["user@example.com"]
    assert out == "<email>"


# ── pii_masker использует fast-path ──────────────────────────────────────


def test_pii_masker_uses_sub_email_fastpath(monkeypatch: pytest.MonkeyPatch) -> None:
    """``PIIMasker.mask_text`` обязан звать ``sub_email`` для email-паттерна."""
    calls: list[str] = []

    def _fake_sub_email(repl: Any, value: str) -> str:
        calls.append(value)
        return pii_patterns.sub_email(repl, value)

    monkeypatch.setattr(pii_masker, "sub_email", _fake_sub_email, raising=False)

    out = pii_masker.default_masker().mask_text("mail me at bob@example.com")

    assert calls == ["mail me at bob@example.com"]
    assert out == "mail me at ***"
