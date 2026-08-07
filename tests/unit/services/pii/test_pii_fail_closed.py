"""Regression tests для PII fail-CLOSED contract (cycle-4/D-AUDIT-109).

Проверяет, что при sanitizer failure:
1. ``PIIFailClosedError`` поднимается (НЕ silent return raw PII);
2. Audit event ``pii.sanitizer_failure`` emitted;
3. ``__cause__`` содержит оригинальное исключение (через ``raise ... from exc``);
4. Helper :func:`raise_pii_fail_closed` всегда raises (annotated ``NoReturn``).

Covers:
- :func:`src.backend.core.policy.pii_fail_closed.raise_pii_fail_closed`;
- :meth:`src.backend.services.pii.facade.PIIFacade.mask`;
- :meth:`src.backend.services.pii.facade.PIIFacade.tokenize`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.core.policy.pii_fail_closed import (
    PIIFailClosedError,
    raise_pii_fail_closed,
)


class _FailingMasker:
    """Sanitizer-стаб, всегда raises."""

    def mask_text(self, text: str) -> str:  # noqa: ARG002
        raise RuntimeError("simulated masker failure")


class TestRaisePiiFailClosed:
    """Tests для ``raise_pii_fail_closed`` helper."""

    def test_raises_pii_fail_closed_error(self) -> None:
        """``raise_pii_fail_closed`` всегда raises PIIFailClosedError."""
        with pytest.raises(PIIFailClosedError) as caught:
            raise_pii_fail_closed(
                source="test.source",
                payload_size=42,
                exc=RuntimeError("boom"),
            )
        # Source propagated as args[0].
        assert caught.value.args[0] == "test.source"

    def test_chains_original_exception(self) -> None:
        """``__cause__`` содержит оригинальное исключение (raise from exc)."""
        original = ValueError("original error")
        with pytest.raises(PIIFailClosedError) as caught:
            raise_pii_fail_closed(
                source="test.source", payload_size=10, exc=original
            )
        assert caught.value.__cause__ is original
        assert isinstance(caught.value.__cause__, ValueError)

    def test_emits_audit_event(self) -> None:
        """Audit event ``pii.sanitizer_failure`` emitted через log_audit_event_lite."""
        with patch(
            "src.backend.core.observability.logging_helpers.log_audit_event_lite"
        ) as mock_audit:
            with pytest.raises(PIIFailClosedError):
                raise_pii_fail_closed(
                    source="audit.test",
                    payload_size=100,
                    exc=RuntimeError("boom"),
                )
            mock_audit.assert_called_once()
            kwargs = mock_audit.call_args.kwargs
            assert kwargs["event"] == "pii.sanitizer_failure"
            assert kwargs["source"] == "audit.test"
            assert kwargs["payload_size"] == 100
            assert kwargs["error_class"] == "RuntimeError"
            assert kwargs["severity"] == "error"

    def test_audit_failure_does_not_mask_pii_failure(self) -> None:
        """Если audit emit падает — PIIFailClosedError всё равно поднимается."""
        with patch(
            "src.backend.core.observability.logging_helpers.log_audit_event_lite",
            side_effect=RuntimeError("audit boom"),
        ):
            with pytest.raises(PIIFailClosedError):
                raise_pii_fail_closed(
                    source="test.audit.fail",
                    payload_size=10,
                    exc=RuntimeError("original"),
                )


class TestPIIFacadeMaskFailClosed:
    """``PIIFacade.mask`` raises PIIFailClosedError on sanitizer failure."""

    def test_mask_raises_on_masker_failure(self) -> None:
        """cycle-4/D-AUDIT-109: mask raises PIIFailClosedError, НЕ returns raw."""
        from src.backend.services.pii.facade import PIIFacade

        facade = PIIFacade()
        # Patch _masker so that mask_text raises.
        with patch.object(facade, "_masker", _FailingMasker()):
            with pytest.raises(PIIFailClosedError) as caught:
                facade.mask("test@example.com")
            assert caught.value.args[0] == "pii.facade.mask"
            assert isinstance(caught.value.__cause__, RuntimeError)
            assert "simulated masker failure" in str(caught.value.__cause__)

    def test_tokenize_raises_on_masker_failure(self) -> None:
        """cycle-4/D-AUDIT-109: tokenize raises PIIFailClosedError, НЕ returns raw."""
        from src.backend.services.pii.facade import PIIFacade

        facade = PIIFacade()
        with patch.object(facade, "_masker", _FailingMasker()):
            with pytest.raises(PIIFailClosedError) as caught:
                facade.tokenize("test@example.com")
            assert caught.value.args[0] == "pii.facade.tokenize"
            assert isinstance(caught.value.__cause__, RuntimeError)

    def test_mask_struct_still_fail_open_out_of_scope(self) -> None:
        """``mask_struct`` не в scope T-W1-09 — поведение сохранено (fail-OPEN).

        Per plan: ``mask()`` и ``tokenize()`` только.
        """
        from src.backend.services.pii.facade import PIIFacade

        facade = PIIFacade()
        with patch.object(facade, "_masker", _FailingMasker()):
            # mask_struct НЕ модифицирован в T-W1-09 — возвращает input.
            result = facade.mask_struct({"email": "x@y.z"})
            assert result == {"email": "x@y.z"}