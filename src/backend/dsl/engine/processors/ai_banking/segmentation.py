"""Customer segmentation processor — мигрирован из S59 banking_processors на S50 base."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.backend.core.audit.facade import emit_banking_audit
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.ai_banking._base import _BankingAIProcessor


class CustomerSegmentationResult(BaseModel):
    """Результат сегментации клиента."""

    segment: str = Field(description="mass / affluent / business / vip / new")
    confidence: float = Field(ge=0.0, le=1.0, description="Уверенность в сегментации")
    characteristics: list[str] = Field(
        default_factory=list, description="Характеристики сегмента"
    )
    recommended_products: list[str] = Field(
        default_factory=list, description="Рекомендованные продукты"
    )


class CustomerSegmentationProcessor(_BankingAIProcessor):
    """Сегментация клиентов — отнесение к банковскому сегменту.

    Вход: {"demographics": str, "account_activity": str,
           "product_holdings": str, "channel_preference": str}.
    Выход: {"segment": str, "confidence": float,
            "characteristics": [...], "recommended_products": [...]}.
    """

    capability = "ai.banking.segmentation"
    audit_event_prefix = "banking.segmentation"

    def __init__(self, model: str | None = None) -> None:
        super().__init__(name="customer_segmentation")
        self.model = model

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Классифицирует клиента в сегмент через LLM с audit-событиями."""
        exchange.set_property("banking_action", "ai.segmentation.classify")
        body = exchange.in_message.body
        if not isinstance(body, dict):
            exchange.fail("CustomerSegmentationProcessor: expected dict body")
            return
        prompt = self._build_prompt(body)
        if not await self._check_capability(exchange, context):
            return
        result = await self._call_llm(
            prompt=prompt,
            output_model=CustomerSegmentationResult,
            exchange=exchange,
            context=context,
            model=self.model,
        )
        if result is None:
            await emit_banking_audit(
                event=f"{self.audit_event_prefix}.failed",
                processor=self.name,
                params={},
                error="llm_call_failed",
            )
            return
        await emit_banking_audit(
            event=f"{self.audit_event_prefix}.completed",
            processor=self.name,
            params={},
            result={
                "segment": result.segment,
                "confidence": result.confidence,
            },
        )
        exchange.in_message.set_body(
            {
                "segment": result.segment,
                "confidence": result.confidence,
                "characteristics": result.characteristics,
                "recommended_products": result.recommended_products,
            }
        )
        exchange.set_property("customer_segment", result.segment)

    def _build_prompt(self, body: dict[str, Any]) -> str:
        return (
            "Определи сегмент клиента и порекомендуй продукты.\n\n"
            f"- демография: {body.get('demographics', '')}\n"
            f"- активность: {body.get('account_activity', '')}\n"
            f"- текущие продукты: {body.get('product_holdings', '')}\n"
            f"- предпочитаемый канал: {body.get('channel_preference', '')}\n\n"
            "Верни JSON:\n"
            '{\n'
            '  "segment": "mass|affluent|business|vip|new",\n'
            '  "confidence": 0.0-1.0,\n'
            '  "characteristics": ["char1", "char2"],\n'
            '  "recommended_products": ["product1", "product2"]\n'
            '}'
        )

    async def _check_capability(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> bool:
        try:
            from src.backend.core.security.capabilities import CapabilityGate

            gate = CapabilityGate()
            gate.check(self.capability, scope=None)
            return True
        except Exception as exc:
            exchange.fail(f"capability_denied: {self.capability} - {exc}")
            await emit_banking_audit(
                event=f"{self.audit_event_prefix}.capability_denied",
                processor=self.name,
                params={},
                error=str(exc),
            )
            return False

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self.model:
            spec["model"] = self.model
        return {"customer_segmentation": spec}
