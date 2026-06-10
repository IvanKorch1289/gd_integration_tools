from __future__ import annotations
"""S59 W1 — risk.py part of banking_processors decomp.

Classes: RiskAssessmentProcessor.

Risk assessment processor.
"""

from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.registry import processor
from src.backend.dsl.engine.processors.ai.banking_processors.base import _BankingAIProcessor  # S59 W1: base for processors
from src.backend.dsl.engine.processors.ai.banking_processors.results import RiskAssessmentResult  # S59 W1: result schema



if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_logger = get_logger("dsl.processors.ai.banking")

# ─── Pydantic schemas for structured output ─────────────────────────────────

class RiskAssessmentProcessor(_BankingAIProcessor):
    """Оценка рисков — комплексная оценка рисков по заявке.

    Вход (body):
        customer_profile: str — профиль клиента (свободный текст)
        loan_amount: float — запрошенная сумма кредита
        loan_purpose: str — цель кредита
        collateral_value: float — стоимость залога (0 если без залога)
        market_conditions: str — текущие рыночные условия

    Выход (body.riskassessment):
        risk_level: str — low / medium / high / critical
        risk_score: float (0.0-1.0) — численный score риска
        risk_factors: list[str] — ключевые факторы риска
        mitigation_suggestions: list[str] — рекомендации по снижению риска

    Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
    """

    ResultSchema = RiskAssessmentResult

    prompt_template = """Проведи комплексную оценку рисков по кредитной заявке.

Данные заявки:
- профиль клиента: ${body.customer_profile}
- запрошенная сумма: ${body.loan_amount}
- цель кредита: ${body.loan_purpose}
- стоимость залога: ${body.collateral_value}
- рыночные условия: ${body.market_conditions}

Верни JSON со следующими полями:
- risk_level: str — "low" если score < 0.3, "medium" если 0.3-0.5, "high" если 0.5-0.7, "critical" если > 0.7
- risk_score: float (0.0-1.0) — комплексный score риска
- risk_factors: list[str] — 2-4 ключевых фактора риска
- mitigation_suggestions: list[str] — 2-3 рекомендации по снижению риска

Отвечай ТОЛЬКО валидным JSON, соответствующим схеме."""

