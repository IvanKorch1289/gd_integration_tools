"""S59 W1 — results.py part of banking_processors decomp.

Classes: CreditScoreResult, FraudDetectionResult, RiskAssessmentResult, CustomerSegmentationResult, LoanEligibilityResult.

5 Pydantic result schemas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    pass

_logger = get_logger("dsl.processors.ai.banking")

# ─── Pydantic schemas for structured output ─────────────────────────────────


class CreditScoreResult(BaseModel):
    """Результат кредитного скоринга."""

    score: int = Field(..., ge=300, le=850, description="Кредитный балл (FICO)")
    decision: str = Field(..., description="Решение: approve / review / reject")
    reasons: list[str] = Field(default_factory=list, description="Ключевые факторы")
    risk_factors: list[str] = Field(default_factory=list, description="Факторы риска")


class FraudDetectionResult(BaseModel):
    """Результат детекции фрода."""

    fraud_score: float = Field(..., ge=0.0, le=1.0, description="Вероятность фрода")
    is_suspicious: bool = Field(..., description="Флаг подозрительности")
    fraud_indicators: list[str] = Field(
        default_factory=list, description="Найденные индикаторы"
    )
    recommended_action: str = Field(..., description="Рекомендуемое действие")


class RiskAssessmentResult(BaseModel):
    """Результат оценки рисков."""

    risk_level: str = Field(
        ..., description="Уровень риска: low / medium / high / critical"
    )
    risk_score: float = Field(..., ge=0.0, le=1.0, description="Численный score риска")
    risk_factors: list[str] = Field(default_factory=list, description="Факторы риска")
    mitigation_suggestions: list[str] = Field(
        default_factory=list, description="Рекомендации по снижению"
    )


class CustomerSegmentationResult(BaseModel):
    """Результат сегментации клиента."""

    segment: str = Field(
        ..., description="Сегмент: mass / affluent / business / vip / new"
    )
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Уверенность в сегментации"
    )
    characteristics: list[str] = Field(
        default_factory=list, description="Характеристики сегмента"
    )
    recommended_products: list[str] = Field(
        default_factory=list, description="Рекомендованные продукты"
    )


class LoanEligibilityResult(BaseModel):
    """Результат проверки eligibility для кредита."""

    eligible: bool = Field(..., description="Одобрен ли кредит")
    max_amount: float = Field(..., ge=0.0, description="Максимальная сумма")
    interest_rate: float = Field(..., ge=0.0, description="Процентная ставка")
    term_months: int = Field(..., ge=1, description="Срок в месяцах")
    decision_reasons: list[str] = Field(
        default_factory=list, description="Основные причины решения"
    )
    conditions: list[str] = Field(default_factory=list, description="Условия кредита")
