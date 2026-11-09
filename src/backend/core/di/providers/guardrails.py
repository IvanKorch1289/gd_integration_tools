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
