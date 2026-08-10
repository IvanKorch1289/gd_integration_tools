"""Banking AI base processor (S50 W3 extraction).

Extracted from ``ai_banking.py`` god-file (828 LOC).
Backward-compat: re-exported via ``ai_banking/__init__.py``.

S190: добавлен helper ``_check_capability_via_facade`` для миграции
inline ``gate.check()`` pattern → unified ``CapabilityFacade.check_or_raise``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

import orjson
from pydantic import BaseModel

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("_BankingAIProcessor",)

_logger = get_logger("dsl.engine.processors.ai_banking")
_T = TypeVar("_T", bound=BaseModel)


class _BankingAIProcessor(BaseProcessor):
    """Base class for banking AI processors with common LLM logic."""

    capability: str = "ai.banking.base"
    audit_event_prefix: str = "banking"
    COST_PER_1K_TOKENS: float = 0.02

    async def _check_capability_via_facade(
        self,
        exchange: Exchange[Any],
    ) -> bool:
        """S190: unified capability check через CapabilityFacade.

        Заменяет inline ``gate.check(self.capability, scope=None)`` pattern
        в banking processors на единый facade call. Преимущества:
        - Plugin attribution (audit logging знает кто вызвал)
        - Scope binding (может быть tenant_id)
        - Fail-closed semantics через CapabilityDeniedError
        - Переиспользует ту же facade что extensions и DSL routes

        Returns:
            True если capability granted. На deny — exchange.fail()
            с emit banking audit event.

        """
        try:
            from src.backend.services.capabilities.facade import get_capability_facade

            get_capability_facade().check_or_raise(
                plugin=f"dsl.engine.processors.ai_banking.{self.__class__.__name__}",
                capability=self.capability,
                scope=None,
            )
            return True
        except Exception as exc:
            from src.backend.core.security.capabilities import CapabilityDeniedError

            if isinstance(exc, CapabilityDeniedError):
                exchange.fail(f"capability_denied: {self.capability}")
                # CapabilityDeniedError emit audit, не нужно дубль
                return False

            # Other exception — log + fail
            exchange.fail(f"capability_check_error: {self.capability} - {exc}")
            _logger.warning(
                "banking capability check failed: %s - %s",
                self.capability,
                exc,
            )
            return False

    async def _call_llm(
        self,
        prompt: str,
        output_model: type[_T],
        exchange: Exchange[Any],
        context: ExecutionContext,
        model: str | None = None,
    ) -> _T | None:
        """Execute LLM call with structured output.

        Returns:
            Parsed Pydantic model or None on failure.

        """
        from src.backend.core.resilience.retry import make_async_retry

        try:
            from src.backend.services.ai.ai_agent import (  # noqa: F401 — availability probe
                get_ai_agent_service,
            )
        except ImportError as exc:
            exchange.fail(f"AI agent service unavailable: {exc}")
            return None
        agent = get_ai_agent_service()
        _retryable = (TimeoutError, ConnectionError)

        @make_async_retry(
            max_attempts=3, initial_backoff=1.0, multiplier=2.0, on=_retryable,
        )
        async def _chat_with_retry() -> Any:
            return await agent.chat(
                messages=[{"role": "user", "content": prompt}],
                model=model or "default",
                response_format=output_model,
            )

        try:
            raw = await _chat_with_retry()
        except RuntimeError as exc:
            if "rate" in str(exc).lower():
                exchange.fail(f"LLM rate limit: {exc}")
            else:
                exchange.fail(f"LLM call failed: {exc}")
            return None
        except (TimeoutError, ConnectionError) as exc:
            exchange.fail(f"LLM call failed after retries: {exc}")
            return None
        if isinstance(raw, dict):
            usage = raw.get("usage") or {}
            tokens = int(usage.get("total_tokens", 0)) if usage else 0
            if tokens:
                cost = round(tokens * self.COST_PER_1K_TOKENS / 1000, 6)
                exchange.set_property("llm.tokens_used", tokens)
                exchange.set_property("llm.cost_usd", cost)
                exchange.set_property("banking.cost_usd", cost)
        if isinstance(raw, dict):
            try:
                return output_model.model_validate(raw)
            except Exception as exc:
                _logger.warning("structured_output_parse_error: %s", exc)
                return self._parse_fallback(raw, output_model)
        if isinstance(raw, str):
            return self._parse_fallback({"text": raw}, output_model)
        return None

    def _parse_fallback(self, raw: dict[str, Any], output_model: type[_T]) -> _T | None:
        """Fallback parsing when structured output fails."""
        text = raw.get("text", "") if isinstance(raw, dict) else str(raw)
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                parsed = orjson.loads(text[start:end])
                return output_model.model_validate(parsed)
            except (ValueError, TypeError, orjson.JSONDecodeError) as parse_exc:
                # cycle-9/D-AUDIT-1723: narrow exceptions + observability.
                # ValueError — malformed JSON, TypeError — wrong payload
                # type, orjson.JSONDecodeError (subclass of ValueError)
                # — explicitly captured for clarity.
                import logging
                logging.getLogger(__name__).debug(
                    "ai_banking._base.json_parse_failed",
                    extra={"error": str(parse_exc)},
                )
        return None
