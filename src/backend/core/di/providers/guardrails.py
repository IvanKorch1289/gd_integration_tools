"""DI-провайдер сервиса метрик guardrails (ADR-0432).

``GuardrailsMetricsService`` агрегирует вердикты guardrails (block/redact/
false-positive) по тенантам. До ADR-0432 сервис существовал, но не был
подключён: DI-провайдера не было, HTTP-эндпоинта не было → метрики
не собирались и не отдавались.

Провайдер отдаёт **процессный singleton**: агрегатор in-memory, и новый
экземпляр на каждый вызов обнулял бы накопленное.
"""

from __future__ import annotations

from typing import Any

__all__ = (
    "get_guardrails_metrics_service_provider",
    "record_guardrail_verdict",
    "set_guardrails_metrics_service_provider",
)

_overrides: dict[str, Any] = {}


def get_guardrails_metrics_service_provider() -> Any:
    """Вернуть singleton :class:`GuardrailsMetricsService`.

    Returns:
        Экземпляр сервиса метрик guardrails (или override из тестов).

    """
    if "guardrails_metrics_service" in _overrides:
        return _overrides["guardrails_metrics_service"]
    from src.backend.services.ai.guardrails_metrics import GuardrailsMetricsService

    service = _overrides.get("guardrails_metrics_singleton")
    if service is None:
        service = GuardrailsMetricsService()
        _overrides["guardrails_metrics_singleton"] = service
    return service


def set_guardrails_metrics_service_provider(service: Any) -> None:
    """Установить override сервиса метрик guardrails (test-инжекция).

    Args:
        service: Экземпляр сервиса (или ``None`` — сброс override'а).

    """
    if service is None:
        _overrides.pop("guardrails_metrics_service", None)
        _overrides.pop("guardrails_metrics_singleton", None)
        return
    _overrides["guardrails_metrics_service"] = service


async def record_guardrail_verdict(
    *, tenant_id: str, verdict: str, model_used: str = "unknown"
) -> None:
    """Записать вердикт guardrails в агрегатор метрик (best-effort).

    Точка входа для слоя ``core``: маппинг строки в enum живёт здесь, чтобы
    вызывающий модуль не импортировал ``services`` (межслойный импорт).

    Args:
        tenant_id: Тенант-владелец.
        verdict: ``"safe"`` / ``"blocked"`` / ``"warn"`` / ``"redact"``.
        model_used: Модель, на которой сработал guardrail.

    """
    from src.backend.services.ai.guardrails_metrics import GuardrailVerdict

    if verdict not in ("safe", "blocked", "warn", "redact"):
        return
    mapped = (
        GuardrailVerdict.BLOCK
        if verdict == "blocked"
        else GuardrailVerdict.REDACT
        if verdict == "redact"
        else GuardrailVerdict.ALLOW
    )
    service = get_guardrails_metrics_service_provider()
    await service.record(
        tenant_id=tenant_id or "unknown",
        verdict=mapped,
        model_used=model_used or "unknown",
    )
