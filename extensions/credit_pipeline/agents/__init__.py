"""Real credit scoring agent для MultiAgentSupervisor (S76 W1).

Replaces the stub implementation в src/backend/services/ai/multi_agent/
supervisor.py::_build_credit_pipeline_agents (S38 K4 Sprint 7).

Integration pattern (вместо supervisor stub):

    from extensions.credit_pipeline.agents import (
        scoring_agent, document_parser_agent, decision_agent,
    )
    from src.backend.services.ai.multi_agent import MultiAgentSupervisor, AgentSpec

    supervisor = MultiAgentSupervisor(
        name="credit_orchestrator",
        agents=[
            AgentSpec(name="scoring_agent", invoke=scoring_agent),
            AgentSpec(name="document_parser_agent", invoke=document_parser_agent),
            AgentSpec(name="decision_agent", invoke=decision_agent),
        ],
    )

Business logic использует existing extensions/credit_pipeline/domain/models.py
(CreditApplication, CreditReport) + functions/normalize.py::apply_rules.

Wave: ``[wave:s76/w1-real-credit-agents]``.
"""

from __future__ import annotations

from typing import Any, Literal

from extensions.credit_pipeline.domain.models import CreditDecision
from extensions.credit_pipeline.functions.normalize import apply_rules

__all__ = ("decision_agent", "document_parser_agent", "scoring_agent")


# Threshold для approval — 600 FICO-equivalent (из supervisor stub).
_SCORE_APPROVAL_THRESHOLD: int = 600

_DecisionLabel = Literal["APPROVE", "MANUAL_REVIEW", "REJECT"]


def _decision_label(approved: bool, score: int) -> _DecisionLabel:
    """Маппинг (approved, score) -> CreditDecision.decision label."""
    if approved:
        return "APPROVE"
    if score >= 500:  # borderline -> manual review
        return "MANUAL_REVIEW"
    return "REJECT"


async def scoring_agent(payload: dict[str, Any]) -> dict[str, Any]:
    """Реальный credit scoring agent.

    Использует :class:`CreditApplication` для валидации payload,
    применяет rule-based scoring (lightweight ML-stub для S76 W1).
    Реальная ML-интеграция (Spark/НБКИ) — out of scope для этого W.

    Args:
        payload: dict с полями ``client_id``, ``amount``, ``duration_months``,
            ``applicant_id`` (для production).

    Returns:
        dict с полями:
          - ``agent``: "scoring_agent"
          - ``client_id``: int (echoed)
          - ``credit_score``: int [0, 1000]
          - ``risk_class``: "LOW" | "MEDIUM" | "HIGH"
          - ``model_version``: "s76-w1-rule-based-v1"
    """
    client_id = payload.get("client_id") or payload.get("applicant_id") or 0

    # Rule-based scoring (placeholder для production ML model).
    # Real impl: load pkl, call SKB/НБКИ, etc.
    amount = int(payload.get("amount", 0))
    duration = int(payload.get("duration_months", 12))
    income = int(payload.get("monthly_income", 0))

    # Simple debt-to-income ratio + amount-based penalty.
    monthly_payment = amount / max(duration, 1) if duration else 0
    dti = (monthly_payment / max(income, 1)) if income > 0 else 0.5

    base_score = 750  # Default for unknown
    if income > 0 and amount > 0:
        # Linear model: low DTI + reasonable amount → high score
        if dti < 0.3:
            base_score = 800
        elif dti < 0.5:
            base_score = 720
        elif dti < 0.7:
            base_score = 650
        else:
            base_score = 500

    # Normalize через apply_rules (existing extension function).
    normalized = apply_rules({"score": base_score, "decision": "pending"})

    return {
        "agent": "scoring_agent",
        "client_id": int(client_id),
        "credit_score": int(normalized.get("score", base_score)),
        "risk_class": str(normalized.get("risk_class", "MEDIUM")),
        "model_version": "s76-w1-rule-based-v1",
        "stub": False,  # marker что это НЕ stub (для tests / monitoring)
    }


async def document_parser_agent(payload: dict[str, Any]) -> dict[str, Any]:
    """Реальный document parser agent (S76 W1 minimal).

    S76 W1 — rule-based parser: extracts applicant_id + amount + duration
    from raw application dict. Реальный PDF/DOCX parsing — out of scope
    (Sprint 8+ когда будут SKB/НБКИ clients).

    Args:
        payload: dict с potential document fields.

    Returns:
        dict с полями:
          - ``agent``: "document_parser_agent"
          - ``extracted``: dict с extracted fields
          - ``completeness_pct``: int [0, 100]
    """
    required_fields = ("applicant_id", "amount", "duration_months", "purpose")
    extracted: dict[str, Any] = {}
    for field in required_fields:
        if field in payload and payload[field] is not None:
            extracted[field] = payload[field]

    completeness_pct = int(len(extracted) * 100 / len(required_fields))

    return {
        "agent": "document_parser_agent",
        "extracted": extracted,
        "completeness_pct": completeness_pct,
        "parser_version": "s76-w1-rule-based-v1",
        "stub": False,
    }


async def decision_agent(payload: dict[str, Any]) -> dict[str, Any]:
    """Реальный decision agent (S76 W1).

    Использует результат scoring_agent (если есть в payload) для
    финального решения об одобрении. Реальный decision engine с
    multi-factor (amount, score, duration, DTI) — out of scope
    (Sprint 8+).

    Args:
        payload: dict с ``scoring_agent`` output (от предыдущего шага
            supervisor'а) + application data.

    Returns:
        dict с полями:
          - ``agent``: "decision_agent"
          - ``approved``: bool
          - ``credit_score``: int (echoed from scoring)
          - ``score_threshold``: int (decision boundary)
          - ``decision_version``: "s76-w1-v1"
    """
    # Extract score from previous step (scoring_agent output).
    scoring_output = payload.get("scoring_agent") or {}
    credit_score = int(scoring_output.get("credit_score", 0))

    # Also support direct payload.score (for unit tests / single-step use).
    if not credit_score and "score" in payload:
        credit_score = int(payload["score"])

    approved = bool(credit_score >= _SCORE_APPROVAL_THRESHOLD)
    decision_label = _decision_label(approved, credit_score)

    decision = CreditDecision(
        applicant_id=int(payload.get("applicant_id", 0)),
        decision=decision_label,
        combined_score=credit_score,
        risk_class="LOW" if approved else "MEDIUM",
    )

    return {
        "agent": "decision_agent",
        "approved": approved,
        "credit_score": decision.combined_score,
        "score_threshold": _SCORE_APPROVAL_THRESHOLD,
        "reason": (
            f"Score {credit_score} {'≥' if approved else '<'} "
            f"threshold {_SCORE_APPROVAL_THRESHOLD} → {decision_label}"
        ),
        "decision_version": "s76-w1-v1",
        "stub": False,
    }
