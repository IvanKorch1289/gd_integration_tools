"""DSL процессор: Применение guardrails (input/output фильтры) для LLM-вызовов."""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

logger = get_logger(__name__)


class GuardrailsProcessor(BaseProcessor):
    """Проверяет LLM output на безопасность и соответствие ожиданиям.

    Валидации: max_length, blocklist regex, required dict keys,
    + опциональные внешние провайдеры Lakera Guard / NeMo Guardrails (Sprint 11 K1 W2;
    Rebuff удалён S172 — см. research/agent-framework/REPORT.md F4.2)
    с per-tenant конфигурацией через TenantContext.

    Активация внешних провайдеров: ``feature_flags.guardrails_per_tenant=True``;
    конфиг берётся из ``providers_config`` или TenantContext-resolver'а.
    """

    def __init__(
        self,
        *,
        max_length: int = 10000,
        blocked_patterns: list[str] | None = None,
        required_fields: list[str] | None = None,
        providers_config: Any = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "guardrails")
        self._max_length = max_length
        self._blocked = blocked_patterns or []
        self._required = required_fields or []
        self._providers_config = providers_config

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Проверяет текст на длину, блок-паттерны и обязательные поля."""
        import re

        body = exchange.in_message.body
        text = body if isinstance(body, str) else str(body)

        if len(text) > self._max_length:
            exchange.fail(
                f"Guardrail: output too long ({len(text)} > {self._max_length})",
            )
            return

        for pattern in self._blocked:
            if re.search(pattern, text, re.IGNORECASE):
                exchange.fail(f"Guardrail: blocked pattern detected: {pattern}")
                return

        if self._required and isinstance(body, dict):
            missing = [f for f in self._required if f not in body]
            if missing:
                exchange.fail(f"Guardrail: missing required fields: {missing}")
                return

        await self._check_external_providers(exchange, text)

    async def _check_external_providers(
        self, exchange: Exchange[Any], text: str,
    ) -> None:
        """Запустить Lakera/Rebuff если активны (Sprint 11 K1 W2)."""
        from src.backend.core.config.features import feature_flags

        if not feature_flags.guardrails_per_tenant:
            # S227 cycle 14 (D433): warn so silent skip is visible — per-tenant
            # guardrails OFF means external provider checks (Lakera/NeMo) are
            # skipped without audit. Operators can correlate via processor name.
            logger.warning(
                "%s: guardrails_per_tenant feature flag disabled — "
                "external provider checks skipped (S227 cycle 14 D433)",
                self.name,
                extra={"guard_name": "feature_flag_off"},
            )
            return
        config = self._resolve_config()
        if not config or not config.enabled_providers:
            # S227 cycle 14 (D433): warn so silent skip is visible — no
            # providers configured for this tenant means external checks
            # are skipped without audit. Operators can correlate via
            # processor name + tenant id from context.
            logger.warning(
                "%s: no guardrails providers configured — "
                "external provider checks skipped (S227 cycle 14 D433)",
                self.name,
                extra={"guard_name": "no_providers_configured"},
            )
            return

        if "lakera" in config.enabled_providers:
            try:
                from src.backend.services.ai.guardrails.lakera_client import (
                    LakeraClient,
                )

                lakera_result = await LakeraClient().screen(text)
                if (
                    lakera_result.flagged
                    and lakera_result.score >= config.thresholds.lakera_threshold
                ):
                    exchange.fail(
                        f"Guardrail/lakera: flagged (score={lakera_result.score:.2f})",
                    )
                    return
            except Exception as exc:
                # S227 cycle 14 (D433): warn so silent exception swallow is
                # visible. Without block_on_failure, the failure is hidden
                # and the request continues — operators need visibility.
                logger.warning(
                    "%s: Lakera provider error (block_on_failure=False, "
                    "continuing without check): %s (S227 cycle 14 D433)",
                    self.name,
                    exc,
                    extra={"guard_name": "lakera", "error": str(exc)},
                )
                if config.block_on_failure:
                    exchange.fail(f"Guardrail/lakera: provider error: {exc}")
                    return

        if "rebuff" in config.enabled_providers:
            # S172: Rebuff archived 2025-05-16 — see
            # research/agent-framework/REPORT.md F4.2.
            # Provider removed; tenant-config retains legacy field
            # ``rebuff_threshold`` for audit back-compat but does not invoke.
            logger.warning(
                "guardrails: rebuff provider requested but archived "
                "(S172). Configure lakera/nemo instead. See "
                "research/agent-framework/REPORT.md F4.2.",
                extra={"guard_name": "rebuff", "category": "guardrail_legacy"},
            )

        if "nemo" in config.enabled_providers:
            try:
                from src.backend.services.ai.guardrails.nemo_client import (
                    get_nemo_guardrails_runtime,
                )

                runtime = await get_nemo_guardrails_runtime()
                if runtime is None:
                    # Cycle 10 swarm (AI-5 hardening): log warning so
                    # silent NeMo-unavailable is visible. Per Analyst #5,
                    # previous silent return was a fail-open risk.
                    # Cycle 75: use module-level canonical logger.
                    logger.warning(
                        "%s: NeMo guardrails runtime unavailable (GPU/FF); "
                        "skipping NeMo check (S227 cycle 10 hardening)",
                        self.name,
                    )
                    return  # GPU/FF unavailable — skip NeMo silently
                prompt = exchange.get_property("llm.original_prompt", "")
                nemo_result = await runtime.check_output(prompt=prompt, completion=text)
                if not nemo_result.get("safe", True):
                    exchange.fail(
                        f"Guardrail/nemo: {nemo_result.get('reason', 'unsafe output')}",
                    )
                    return
            except Exception as exc:
                # S227 cycle 14 (D433): warn so silent exception swallow is
                # visible. Without block_on_failure, the failure is hidden
                # and the request continues — operators need visibility.
                logger.warning(
                    "%s: NeMo provider error (block_on_failure=False, "
                    "continuing without check): %s (S227 cycle 14 D433)",
                    self.name,
                    exc,
                    extra={"guard_name": "nemo", "error": str(exc)},
                )
                if config.block_on_failure:
                    exchange.fail(f"Guardrail/nemo: provider error: {exc}")
                    return

    def _resolve_config(self) -> Any:
        """Возвращает per-tenant guardrails config или None.

        Источники в порядке приоритета:
        1. Explicit ``providers_config`` переданный в конструктор.
        2. Resolver на основе TenantContext (если задан в DI).
        3. ``None`` — guardrails-провайдеры выключены.
        """
        if self._providers_config is not None:
            return self._providers_config
        try:
            from src.backend.core.tenancy import (  # noqa: F401 — availability probe
                current_tenant,
            )
            from src.backend.services.ai.guardrails.tenant_config import (  # noqa: F401 — availability probe
                get_default_config,
            )
        except ImportError:
            return None
        tenant = current_tenant()
        if tenant is None:
            return None
        return get_default_config()
