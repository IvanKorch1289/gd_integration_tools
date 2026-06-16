"""S59 W1 — credit.py part of banking_processors decomp.

Classes: CreditScoreProcessor.

Credit score processor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.ai.banking_processors.base import (
    _BankingAIProcessor,  # S59 W1: base for processors
)
from src.backend.dsl.engine.processors.ai.banking_processors.results import (
    CreditScoreResult,  # S59 W1: result schema
)

if TYPE_CHECKING:
    pass

_logger = get_logger("dsl.processors.ai.banking")

# ─── Pydantic schemas for structured output ─────────────────────────────────


class CreditScoreProcessor(_BankingAIProcessor):
    """Кредитный скоринг — оценка кредитного балла и решения.

    Вход (body):
        customer_id: str — идентификатор клиента
        income: float — годовой доход
        employment_status: str — статус занятости
        debt_to_income: float — отношение долга к доходу
        payment_history: str — история платежей (свободный текст)

    Выход (body.creditscore):
        score: int — кредитный балл 300-850
        decision: str — approve / review / reject
        reasons: list[str] — ключевые факторы
        risk_factors: list[str] — факторы риска

    Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
    """

    ResultSchema = CreditScoreResult

    prompt_template = """Оцени кредитоспособность клиента и выдай структурированный ответ.

Данные клиента:
- customer_id: ${body.customer_id}
- годовой доход: ${body.income}
- статус занятости: ${body.employment_status}
- debt-to-income ratio: ${body.debt_to_income}
- история платежей: ${body.payment_history}

Верни JSON со следующими полями:
- score: int (300-850) — кредитный балл по модели FICO
- decision: str — "approve" если score >= 700, "review" если 600-699, "reject" если < 600
- reasons: list[str] — 2-3 ключевых фактора, влияющих на решение
- risk_factors: list[str] — выявленные факторы риска

Отвечай ТОЛЬКО валидным JSON, соответствующим схеме."""
