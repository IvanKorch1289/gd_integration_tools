"""Auto-generated from ai_processors.py — single processor files."""
from __future__ import annotations

from typing import Any, Callable

import orjson

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

class GuardrailsProcessor(BaseProcessor):
    """Проверяет LLM output на безопасность и соответствие ожиданиям.

    Валидации: max_length, blocklist regex, required dict keys,
    + опциональные внешние провайдеры Lakera Guard / Rebuff (Sprint 11 K1 W2)
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
        import re

        body = exchange.in_message.body
        text = body if isinstance(body, str) else str(body)

        if len(text) > self._max_length:
            exchange.fail(
                f"Guardrail: output too long ({len(text)} > {self._max_length})"
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
        self, exchange: Exchange[Any], text: str
    ) -> None:
        """Запустить Lakera/Rebuff если активны (Sprint 11 K1 W2)."""
        from src.backend.core.config.features import feature_flags

        if not feature_flags.guardrails_per_tenant:
            return
        config = self._resolve_config()
        if not config or not config.enabled_providers:
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
                        f"Guardrail/lakera: flagged (score={lakera_result.score:.2f})"
                    )
                    return
            except Exception as exc:  # noqa: BLE001
                if config.block_on_failure:
                    exchange.fail(f"Guardrail/lakera: provider error: {exc}")
                    return

        if "rebuff" in config.enabled_providers:
            try:
                from src.backend.services.ai.guardrails.rebuff_client import (
                    RebuffClient,
                )

                rebuff_result = await RebuffClient().detect(text)
                if (
                    rebuff_result.injected
                    and rebuff_result.score >= config.thresholds.rebuff_threshold
                ):
                    exchange.fail(
                        f"Guardrail/rebuff: prompt injection (score={rebuff_result.score:.2f})"
                    )
                    return
            except Exception as exc:  # noqa: BLE001
                if config.block_on_failure:
                    exchange.fail(f"Guardrail/rebuff: provider error: {exc}")
                    return

        if "nemo" in config.enabled_providers:
            try:
                from src.backend.services.ai.guardrails.nemo_client import (
                    get_nemo_guardrails_runtime,
                )

                runtime = get_nemo_guardrails_runtime()
                if runtime is None:
                    return  # GPU/FF unavailable — skip NeMo silently
                prompt = exchange.get_property("llm.original_prompt", "")
                nemo_result = await runtime.check_output(prompt=prompt, completion=text)
                if not nemo_result.get("safe", True):
                    exchange.fail(
                        f"Guardrail/nemo: {nemo_result.get('reason', 'unsafe output')}"
                    )
                    return
            except Exception as exc:  # noqa: BLE001
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
            from src.backend.core.tenancy import current_tenant
            from src.backend.services.ai.guardrails.tenant_config import (
                get_default_config,
            )
        except ImportError:
            return None
        tenant = current_tenant()
        if tenant is None:
            return None
        return get_default_config()
