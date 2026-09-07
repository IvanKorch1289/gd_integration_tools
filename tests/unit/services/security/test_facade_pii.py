"""Тесты PiiFacadeMixin (S3 сплит, T3 ratchet: facade_pii 22%→≥90%).

Покрывает: happy-path tokenize/mask через PIITokenizer/PIIMasker,
fail-open ветки с _emit_pii_fail_audit, detokenize passthrough,
capability-_assert на каждом методе.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.security.facade import SecurityFacade


def _facade_with_spy() -> tuple[SecurityFacade, list[tuple[str, str]]]:
    """Facade с записью capability-check вызовов."""
    calls: list[tuple[str, str]] = []
    facade = SecurityFacade(
        capability_check=lambda plugin, action, resource: calls.append(
            (action, resource)
        ),
    )
    return facade, calls


# ── tokenize_pii ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tokenize_pii_success_calls_tokenizer() -> None:
    facade, calls = _facade_with_spy()
    mock_tokenizer = AsyncMock()
    mock_tokenizer.mask_reversible = AsyncMock(return_value=("<PII_NAME_1>", {"m": 1}))

    with patch(
        "src.backend.core.security.pii_tokenizer.PIITokenizer",
        return_value=mock_tokenizer,
    ), patch(
        "src.backend.core.security.pii_tokenizer.PIIPolicy",
        lambda **kw: SimpleNamespace(**kw),
    ):
        result = await facade.tokenize_pii("Иван Иванов")

    assert result == "<PII_NAME_1>"
    mock_tokenizer.mask_reversible.assert_awaited_once()
    # capability-assert выполнен до маскирования
    assert calls == [("security.pii.tokenize", "text")]


@pytest.mark.asyncio
async def test_tokenize_pii_fail_open_returns_raw_and_audits() -> None:
    """Fail-open: при ошибке tokenizer возвращается raw text + audit-event."""
    facade, calls = _facade_with_spy()
    with patch(
        "src.backend.core.security.pii_tokenizer.PIITokenizer",
        side_effect=RuntimeError("tokenizer down"),
    ), patch(
        "src.backend.services.security.facade_pii._emit_pii_fail_audit"
    ) as mock_audit:
        result = await facade.tokenize_pii("секретные данные")

    assert result == "секретные данные"  # fail-open: raw text
    mock_audit.assert_called_once_with("tokenize_pii", mock_audit.call_args[0][1])
    assert calls == [("security.pii.tokenize", "text")]


# ── detokenize_pii ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_detokenize_pii_passthrough() -> None:
    """detokenize_pii — passthrough (unmask требует TokenMap у caller'а)."""
    facade, calls = _facade_with_spy()
    result = await facade.detokenize_pii("<PII_NAME_1>")
    assert result == "<PII_NAME_1>"
    assert calls == [("security.pii.detokenize", "text")]


# ── mask_pii ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mask_pii_success_calls_masker() -> None:
    facade, calls = _facade_with_spy()
    mock_masker = MagicMock()
    mock_masker.mask_text = MagicMock(return_value="Иван И.О.")

    with patch(
        "src.backend.core.security.pii_masker.PIIMasker", return_value=mock_masker
    ):
        result = await facade.mask_pii("Иван Иванов")

    assert result == "Иван И.О."
    mock_masker.mask_text.assert_called_once_with("Иван Иванов")
    assert calls == [("security.pii.mask", "text")]


@pytest.mark.asyncio
async def test_mask_pii_fail_open_returns_raw_and_audits() -> None:
    """Fail-open: при ошибке masker возвращается raw text + audit-event."""
    facade, calls = _facade_with_spy()
    with patch(
        "src.backend.core.security.pii_masker.PIIMasker",
        side_effect=RuntimeError("masker down"),
    ), patch(
        "src.backend.services.security.facade_pii._emit_pii_fail_audit"
    ) as mock_audit:
        result = await facade.mask_pii("мои данные")

    assert result == "мои данные"
    mock_audit.assert_called_once_with("mask_pii", mock_audit.call_args[0][1])
    assert calls == [("security.pii.mask", "text")]


# ── _emit_pii_fail_audit ────────────────────────────────────────────


def test_emit_pii_fail_audit_calls_emit_audit_safe() -> None:
    """Helper формирует audit-event с severity=error и failed_operation."""
    from src.backend.services.security.facade_pii import _emit_pii_fail_audit

    with patch(
        "src.backend.core.audit.facade._base.emit_audit_safe"
    ) as mock_emit:
        _emit_pii_fail_audit("mask_pii", RuntimeError("boom"))
        mock_emit.assert_called_once()
        kwargs = mock_emit.call_args.kwargs
        assert kwargs["event"] == "security.pii.fail_open"
        assert kwargs["severity"] == "error"
        assert kwargs["extra"]["failed_operation"] == "mask_pii"
        assert "boom" in kwargs["extra"]["error_message"]


def test_emit_pii_fail_audit_swallows_audit_errors() -> None:
    """Сбой audit-канала не роняет helper (best-effort by design)."""
    from src.backend.services.security.facade_pii import _emit_pii_fail_audit

    with patch(
        "src.backend.core.audit.facade._base.emit_audit_safe",
        side_effect=RuntimeError("audit down"),
    ):
        _emit_pii_fail_audit("mask_pii", RuntimeError("original"))  # не бросает
