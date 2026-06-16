"""S59 W1 — loan.py part of banking_processors decomp.

Classes: LoanEligibilityProcessor.

Loan eligibility processor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.ai.banking_processors.base import (
    _BankingAIProcessor,  # S59 W1: base for processors
)
from src.backend.dsl.engine.processors.ai.banking_processors.results import (
    LoanEligibilityResult,  # S59 W1: result schema
)

if TYPE_CHECKING:
    pass

_logger = get_logger("dsl.processors.ai.banking")

# ─── Pydantic schemas for structured output ─────────────────────────────────


class LoanEligibilityProcessor(_BankingAIProcessor):
    """Проверка eligibility — определение условий кредита.

    Вход (body):
        credit_score: int — кредитный балл (300-850)
        annual_income: float — годовой доход
        requested_amount: float — запрошенная сумма
        loan_term_months: int — желаемый срок в месяцах
        existing_debt: float — текущий долг
        employment_status: str — статус занятости

    Выход (body.loaneligibility):
        eligible: bool — одобрен ли кредит
        max_amount: float — максимальная одобренная сумма
        interest_rate: float — процентная ставка (годовая)
        term_months: int — рекомендованный срок
        decision_reasons: list[str] — причины решения
        conditions: list[str] — условия кредита

    Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
    """

    ResultSchema = LoanEligibilityResult

    prompt_template = """Определи eligibility для кредита и предложи условия.

Данные заявки:
- кредитный балл: ${body.credit_score}
- годовой доход: ${body.annual_income}
- запрошенная сумма: ${body.requested_amount}
- желаемый срок: ${body.loan_term_months} месяцев
- текущий долг: ${body.existing_debt}
- статус занятости: ${body.employment_status}

Верни JSON со следующими полями:
- eligible: bool — True если кредит одобряется (score >= 620 и DTI < 0.4)
- max_amount: float — максимальная сумма (до 5x годового дохода, но не более 10x при хорошем score)
- interest_rate: float — годовая ставка (8-24% в зависимости от score и суммы)
- term_months: int — рекомендованный срок (12-360)
- decision_reasons: list[str] — 2-3 ключевых причины решения
- conditions: list[str] — 1-3 условия (страховка, залог, etc.)

Отвечай ТОЛЬКО валидным JSON, соответствующим схеме."""
