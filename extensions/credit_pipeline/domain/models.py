"""Domain-модели credit_pipeline (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``. Pydantic-модели
для credit-bus pipeline (заявка → отчёты → итоговое решение).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = (
    "CreditApplication",
    "CreditReport",
    "CreditDecision",
)


class CreditApplication(BaseModel):
    """Заявка на кредит.

    Атрибуты:
        applicant_id: Внутренний ID клиента.
        amount: Запрошенная сумма (рубли).
        duration_months: Срок в месяцах.
        purpose: Целевое назначение.
    """

    applicant_id: int
    amount: int = Field(ge=1000)
    duration_months: int = Field(ge=1, le=360)
    purpose: str = ""


class CreditReport(BaseModel):
    """Отчёт credit-агентства (SKB / НБКИ / CBR).

    Атрибуты:
        provider: ``SKB`` | ``NBKI`` | ``CBR``.
        score: Скор-бал (0..1000).
        raw: Сырой ответ агентства (для аудита).
    """

    provider: Literal["SKB", "NBKI", "CBR"]
    score: int = Field(ge=0, le=1000)
    raw: dict | None = None


class CreditDecision(BaseModel):
    """Финальное кредитное решение.

    Атрибуты:
        applicant_id: ID клиента из заявки.
        decision: ``APPROVE`` | ``MANUAL_REVIEW`` | ``REJECT``.
        combined_score: Объединённый score (см.
            :func:`extensions.credit_pipeline.functions.normalize.calculate_combined_score`).
        risk_class: ``LOW`` | ``MEDIUM`` | ``HIGH``.
    """

    applicant_id: int
    decision: Literal["APPROVE", "MANUAL_REVIEW", "REJECT"]
    combined_score: int = Field(ge=0, le=1000)
    risk_class: Literal["LOW", "MEDIUM", "HIGH"]
