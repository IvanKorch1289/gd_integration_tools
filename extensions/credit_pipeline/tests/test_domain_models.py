# ruff: noqa: S101
"""Unit-тесты Pydantic-моделей credit_pipeline (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from extensions.credit_pipeline.domain.models import (
    CreditApplication,
    CreditDecision,
    CreditReport,
)


def test_credit_application_minimal_valid() -> None:
    """CreditApplication принимает минимальный набор полей."""
    app = CreditApplication(applicant_id=42, amount=100000, duration_months=12)
    assert app.applicant_id == 42
    assert app.amount == 100000
    assert app.duration_months == 12
    assert app.purpose == ""


def test_credit_application_amount_below_min_fails() -> None:
    """``amount < 1000`` — ошибка валидации."""
    with pytest.raises(ValidationError):
        CreditApplication(applicant_id=1, amount=500, duration_months=12)


def test_credit_report_provider_literal_enforced() -> None:
    """provider — литерал из {SKB, NBKI, CBR}."""
    valid = CreditReport(provider="SKB", score=700)
    assert valid.provider == "SKB"
    with pytest.raises(ValidationError):
        CreditReport(provider="UNKNOWN", score=500)  # type: ignore[arg-type]


def test_credit_decision_literal_decision_enforced() -> None:
    """decision — литерал из {APPROVE, MANUAL_REVIEW, REJECT}."""
    valid = CreditDecision(
        applicant_id=1, decision="APPROVE", combined_score=750, risk_class="LOW"
    )
    assert valid.decision == "APPROVE"
    with pytest.raises(ValidationError):
        CreditDecision(
            applicant_id=1,
            decision="DEFER",  # type: ignore[arg-type]
            combined_score=600,
            risk_class="MEDIUM",
        )
