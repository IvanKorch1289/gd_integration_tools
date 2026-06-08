"""Smoke tests для extensions/credit_pipeline/agents (S76 W1).

Проверяют:

1. scoring_agent → returns dict with credit_score, risk_class, stub=False.
2. document_parser_agent → returns dict with extracted, completeness_pct.
3. decision_agent → APPROVE для score >= 600, MANUAL_REVIEW/REJECT ниже.
4. Multi-agent composition: scoring → decision pipeline.
5. Integration с existing domain (CreditDecision validation).
"""

from __future__ import annotations

import asyncio
from typing import Any

from extensions.credit_pipeline.agents import (
    decision_agent,
    document_parser_agent,
    scoring_agent,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_scoring_agent_returns_real_implementation() -> None:
    """scoring_agent возвращает credit_score, risk_class, stub=False."""
    payload = {
        "client_id": 12345,
        "amount": 100_000,
        "duration_months": 12,
        "monthly_income": 80_000,
    }
    result = _run(scoring_agent(payload))
    assert result["agent"] == "scoring_agent"
    assert result["client_id"] == 12345
    assert 0 <= result["credit_score"] <= 1000
    assert result["risk_class"] in ("LOW", "MEDIUM", "HIGH")
    assert result["stub"] is False
    assert result["model_version"] == "s76-w1-rule-based-v1"


def test_scoring_agent_high_income_low_dti() -> None:
    """High income, low DTI → score 750+ (LOW risk)."""
    result = _run(
        scoring_agent(
            {
                "client_id": 1,
                "amount": 50_000,
                "duration_months": 12,
                "monthly_income": 200_000,
            }
        )
    )
    assert result["credit_score"] >= 750
    assert result["risk_class"] == "LOW"


def test_scoring_agent_high_dti_low_score() -> None:
    """High DTI (>0.7) → score ~500 (HIGH risk)."""
    result = _run(
        scoring_agent(
            {
                "client_id": 2,
                "amount": 500_000,
                "duration_months": 12,
                "monthly_income": 50_000,
            }
        )
    )
    # DTI = 500_000/12 / 50_000 = 833% → high DTI
    assert result["credit_score"] < 650


def test_document_parser_extracts_fields() -> None:
    """document_parser extracts applicant_id, amount, duration_months, purpose."""
    payload = {
        "applicant_id": 999,
        "amount": 250_000,
        "duration_months": 24,
        "purpose": "car",
    }
    result = _run(document_parser_agent(payload))
    assert result["agent"] == "document_parser_agent"
    assert result["extracted"]["applicant_id"] == 999
    assert result["extracted"]["amount"] == 250_000
    assert result["completeness_pct"] == 100
    assert result["stub"] is False


def test_document_parser_partial_completeness() -> None:
    """Missing fields → completeness_pct < 100."""
    result = _run(document_parser_agent({"applicant_id": 1}))  # only 1 of 4
    assert result["completeness_pct"] == 25


def test_decision_agent_approve_high_score() -> None:
    """score=750 → approved=True, decision_label=APPROVE."""
    result = _run(decision_agent({"applicant_id": 1, "score": 750}))
    assert result["approved"] is True
    assert result["credit_score"] == 750
    assert "APPROVE" in result["reason"]


def test_decision_agent_reject_low_score() -> None:
    """score=400 → approved=False, decision_label=REJECT."""
    result = _run(decision_agent({"applicant_id": 2, "score": 400}))
    assert result["approved"] is False
    assert "REJECT" in result["reason"]


def test_decision_agent_manual_review_borderline() -> None:
    """score=550 (borderline 500-600) → approved=False, MANUAL_REVIEW."""
    result = _run(decision_agent({"applicant_id": 3, "score": 550}))
    assert result["approved"] is False
    assert "MANUAL_REVIEW" in result["reason"]


def test_decision_agent_chained_with_scoring() -> None:
    """Pipeline: scoring → decision (как в MultiAgentSupervisor)."""
    scoring_payload = {
        "client_id": 100,
        "amount": 100_000,
        "duration_months": 12,
        "monthly_income": 100_000,
    }
    scoring_result = _run(scoring_agent(scoring_payload))
    # Supervisor pattern: scoring output → next agent payload
    decision_payload = {"applicant_id": 100, "scoring_agent": scoring_result}
    decision_result = _run(decision_agent(decision_payload))
    # High income + low DTI → score 750+ → APPROVE
    assert decision_result["approved"] is True
    assert decision_result["credit_score"] >= 750


def test_decision_agent_uses_credit_decision_model() -> None:
    """decision_agent validates via CreditDecision (Pydantic v2)."""
    # If CreditDecision has invalid Literal value, Pydantic raises.
    # Our _decision_label returns one of 3 valid values.
    for score, expected_label in [
        (750, "APPROVE"),
        (550, "MANUAL_REVIEW"),
        (400, "REJECT"),
    ]:
        result = _run(decision_agent({"applicant_id": 1, "score": score}))
        assert expected_label in result["reason"]
