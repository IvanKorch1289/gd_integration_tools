"""T-W1-08 / D-AUDIT-10: scoring fail-closed для unknown tenant (banking-critical).

Раньше ``scoring_agent({})`` возвращал ``credit_score=750`` (LOW risk →
APPROVE) — empty/incomplete payload давал fail-OPEN (PHASE-2-SUMMARY
10-P0-003). Теперь: unknown tenant → score=0, risk=HIGH → REJECT.
"""

from __future__ import annotations

import asyncio
from typing import Any

from extensions.credit_pipeline.agents import decision_agent, scoring_agent


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_scoring_unknown_tenant_rejected() -> None:
    """Empty payload → score=0, risk=HIGH (не APPROVE)."""
    result = _run(scoring_agent({}))
    assert result["credit_score"] == 0
    assert result["risk_class"] == "HIGH"
    assert result["reason"] == "unknown_tenant"
    assert result["stub"] is False


def test_decision_chained_rejects_unknown_tenant() -> None:
    """Pipeline score→decision для unknown tenant → REJECT (не APPROVE)."""
    score = _run(scoring_agent({}))
    decision = _run(
        decision_agent({"applicant_id": 0, "scoring_agent": score})
    )
    assert decision["approved"] is False
    assert "REJECT" in decision["reason"]


def test_scoring_incomplete_payload_rejected() -> None:
    """Payload без monthly_income (но с amount) → REJECT (D-AUDIT-10)."""
    result = _run(
        scoring_agent({"client_id": 7, "amount": 100_000, "duration_months": 12})
    )
    assert result["credit_score"] == 0
    assert result["risk_class"] == "HIGH"
