"""S19 K4 W3 — Banking AI processors (S-L4-1 closure).

Wave ``[wave:s19/k4-w3-banking-ai-processors-impl]``.

Пять AI-процессоров для банковского домена, каждый выполняет LLM-вызов
через instructor/litellm и возвращает структурированный Pydantic-результат:

1. CreditScoreProcessor      — кредитный скоринг (скоринг балл + решение)
2. FraudDetectionProcessor   — детекция фрода (флаги + risk score)
3. RiskAssessmentProcessor   — оценка рисков (risk level + факторы)
4. CustomerSegmentationProcessor — сегментация клиентов (segment + reasoning)
5. LoanEligibilityProcessor  — eligibility для кредита (одобрение + условия)

Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
Все процессоры require capability ``ai.llm.litellm`` и ``net.outbound.litellm:external``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, Field

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = (
    "CreditScoreProcessor",
    "FraudDetectionProcessor",
    "RiskAssessmentProcessor",
    "CustomerSegmentationProcessor",
    "LoanEligibilityProcessor",
)


_logger = logging.getLogger("dsl.processors.ai.banking")

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


# ─── Base mixin for LLM-calling banking processors ───────────────────────────


class _BankingAIProcessor(BaseProcessor):
    """Base for banking AI processors — общая логика LLM-вызова."""

    # Override in subclass
    ResultSchema: type[BaseModel] = BaseModel
    prompt_template: str = ""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self, model: str = "anthropic/claude-sonnet-4-6", *, name: str | None = None
    ) -> None:
        super().__init__(name=name or self.__class__.__name__)
        if not model or "/" not in model:
            raise ValueError(
                f"{self.__class__.__name__}: model должен быть в формате "
                f"'<provider>/<name>', получено {model!r}"
            )
        self._model = model
        self._provider = model.split("/", 1)[0]

    def _build_prompt(self, exchange: "Exchange[Any]") -> str:
        """Строит prompt из шаблона с подстановкой ${body.field}."""
        body = exchange.in_message.body
        body_dict = body if isinstance(body, dict) else {"_raw": body}

        import re

        pattern = re.compile(r"\$\{([^}]+)\}")

        def _replace(match: "re.Match[str]") -> str:
            path = match.group(1).strip()
            if path == "body":
                return str(body)
            if path.startswith("body."):
                key = path[len("body.") :]
                return str(body_dict.get(key, ""))
            if path.startswith("properties."):
                key = path[len("properties.") :]
                return str(exchange.properties.get(key, ""))
            return match.group(0)

        return pattern.sub(_replace, self.prompt_template)

    def _write_result(self, exchange: "Exchange[Any]", result: BaseModel) -> None:
        """Пишет Pydantic-результат в body.<field>."""
        field_name = self.__class__.__name__.replace("Processor", "").lower()
        body = exchange.in_message.body
        if not isinstance(body, dict):
            body = {}
        body[field_name] = result.model_dump()
        exchange.in_message.body = body

    @handle_processor_error
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        # Feature gate
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.banking_ai_processors_enabled:
                exchange.set_property(f"{self.name}_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        prompt = self._build_prompt(exchange)

        try:
            import instructor  # type: ignore[import-not-found]
            import litellm  # type: ignore[import-not-found]
        except ImportError as exc:
            exchange.fail(
                f"{self.name}: instructor/litellm не установлены; "
                f"добавьте extras 'ai-2026' (uv sync --extra ai-2026): {exc}"
            )
            return

        from src.backend.infrastructure.resilience.retry import make_async_retry

        client = instructor.from_litellm(litellm.acompletion)

        @make_async_retry(
            max_attempts=2,
            initial_backoff=1.0,
            multiplier=2.0,
            on=(ConnectionError, TimeoutError),
        )
        async def _call() -> BaseModel:
            return await client.create(
                model=self._model,
                response_model=self.ResultSchema,
                messages=[{"role": "user", "content": prompt}],
                max_retries=3,
                temperature=0.0,
            )

        try:
            result = await _call()
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "%s failed: model=%s provider=%s error=%s",
                self.name,
                self._model,
                self._provider,
                exc,
            )
            exchange.fail(f"{self.name} failed: {exc}")
            return

        # Cost tracking
        exchange.set_property("llm.provider", self._provider)
        exchange.set_property("llm.model", self._model)
        exchange.set_property(
            "banking_action", f"ai.banking.{self.name.lower().replace('processor', '')}"
        )

        self._write_result(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        return {
            self.__class__.__name__.lower().replace("processor", "_ai"): {
                "model": self._model
            }
        }


# ─── CreditScoreProcessor ────────────────────────────────────────────────────


@processor(
    "credit_score",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "model": {"type": "string"},
            "customer_id": {"type": "string"},
            "income": {"type": "number"},
            "employment_status": {"type": "string"},
            "debt_to_income": {"type": "number"},
            "payment_history": {"type": "string"},
        },
        "required": ["model"],
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "s19"},
    tags=("ai", "banking", "credit", "scoring"),
)
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


# ─── FraudDetectionProcessor ────────────────────────────────────────────────


@processor(
    "fraud_detection",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "model": {"type": "string"},
            "transaction_amount": {"type": "number"},
            "transaction_type": {"type": "string"},
            "merchant_category": {"type": "string"},
            "location": {"type": "string"},
            "account_age_days": {"type": "integer"},
            "recent_transactions": {"type": "integer"},
        },
        "required": ["model"],
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "s19"},
    tags=("ai", "banking", "fraud", "detection"),
)
class FraudDetectionProcessor(_BankingAIProcessor):
    """Детекция фрода — анализ транзакции на признаки мошенничества.

    Вход (body):
        transaction_amount: float — сумма транзакции
        transaction_type: str — тип (card_present, online, wire, etc.)
        merchant_category: str — категория мерчанта (MCC)
        location: str — локация транзакции
        account_age_days: int — возраст аккаунта в днях
        recent_transactions: int — количество транзакций за последние 24ч

    Выход (body.frauddetection):
        fraud_score: float (0.0-1.0) — вероятность фрода
        is_suspicious: bool — флаг подозрительности
        fraud_indicators: list[str] — найденные индикаторы фрода
        recommended_action: str — allow / block / review

    Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
    """

    ResultSchema = FraudDetectionResult

    prompt_template = """Проанализируй транзакцию на признаки мошенничества.

Данные транзакции:
- сумма: ${body.transaction_amount}
- тип: ${body.transaction_type}
- категория мерчанта: ${body.merchant_category}
- локация: ${body.location}
- возраст аккаунта: ${body.account_age_days} дней
- транзакций за 24ч: ${body.recent_transactions}

Верни JSON со следующими полями:
- fraud_score: float (0.0-1.0) — вероятность фрода
- is_suspicious: bool — True если fraud_score > 0.7
- fraud_indicators: list[str] — список найденных индикаторов фрода
- recommended_action: str — "allow" если score < 0.3, "review" если 0.3-0.7, "block" если > 0.7

Отвечай ТОЛЬКО валидным JSON, соответствующим схеме."""


# ─── RiskAssessmentProcessor ─────────────────────────────────────────────────


@processor(
    "risk_assessment",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "model": {"type": "string"},
            "customer_profile": {"type": "string"},
            "loan_amount": {"type": "number"},
            "loan_purpose": {"type": "string"},
            "collateral_value": {"type": "number"},
            "market_conditions": {"type": "string"},
        },
        "required": ["model"],
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "s19"},
    tags=("ai", "banking", "risk", "assessment"),
)
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


# ─── CustomerSegmentationProcessor ───────────────────────────────────────────


@processor(
    "customer_segmentation",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "model": {"type": "string"},
            "demographics": {"type": "string"},
            "account_activity": {"type": "string"},
            "product_holdings": {"type": "string"},
            "channel_preference": {"type": "string"},
        },
        "required": ["model"],
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "s19"},
    tags=("ai", "banking", "customer", "segmentation"),
)
class CustomerSegmentationProcessor(_BankingAIProcessor):
    """Сегментация клиентов — отнесение клиента к банковскому сегменту.

    Вход (body):
        demographics: str — демографические данные
        account_activity: str — активность по счетам (свободный текст)
        product_holdings: str — текущие продукты клиента
        channel_preference: str — предпочитаемый канал взаимодействия

    Выход (body.customersegmentation):
        segment: str — mass / affluent / business / vip / new
        confidence: float (0.0-1.0) — уверенность в сегментации
        characteristics: list[str] — характеристики сегмента
        recommended_products: list[str] — рекомендованные продукты

    Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
    """

    ResultSchema = CustomerSegmentationResult

    prompt_template = """Определи сегмент клиента и порекомендуй продукты.

Данные клиента:
- демография: ${body.demographics}
- активность: ${body.account_activity}
- текущие продукты: ${body.product_holdings}
- предпочитаемый канал: ${body.channel_preference}

Верни JSON со следующими полями:
- segment: str — "mass" (обычные клиенты), "affluent" (состоятельные), "business" (бизнес), "vip" (премиум), "new" (новые)
- confidence: float (0.0-1.0) — уверенность в определении сегмента
- characteristics: list[str] — 2-3 характеристики определённого сегмента
- recommended_products: list[str] — 2-3 рекомендованных продукта для этого сегмента

Отвечай ТОЛЬКО валидным JSON, соответствующим схеме."""


# ─── LoanEligibilityProcessor ────────────────────────────────────────────────


@processor(
    "loan_eligibility",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "model": {"type": "string"},
            "credit_score": {"type": "integer"},
            "annual_income": {"type": "number"},
            "requested_amount": {"type": "number"},
            "loan_term_months": {"type": "integer"},
            "existing_debt": {"type": "number"},
            "employment_status": {"type": "string"},
        },
        "required": ["model"],
    },
    capabilities=("ai.llm.litellm", "net.outbound.litellm:external"),
    meta={"tier": 2, "category": "ai", "version": "s19"},
    tags=("ai", "banking", "loan", "eligibility"),
)
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
