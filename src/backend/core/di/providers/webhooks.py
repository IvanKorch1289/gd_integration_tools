"""DI-провайдер планировщика webhook'ов (ADR-0432).

``WebhookScheduler`` (services/ops) умеет планировать отложенные/периодические
webhook'ы (Redis-backed), но до ADR-0432 не был подключён: ни DI-провайдера,
ни HTTP-эндпоинтов → портал не мог показать и создать отложенную доставку.
"""

from __future__ import annotations

from typing import Any

__all__ = ("get_webhook_scheduler_provider", "set_webhook_scheduler_provider")

_overrides: dict[str, Any] = {}


def get_webhook_scheduler_provider() -> Any:
    """Вернуть singleton :class:`WebhookScheduler`.

    Returns:
        Экземпляр планировщика webhook'ов (или override из тестов).

    """
    if "webhook_scheduler" in _overrides:
        return _overrides["webhook_scheduler"]
    from src.backend.services.ops.webhook_scheduler import WebhookScheduler

    service = _overrides.get("webhook_scheduler_singleton")
    if service is None:
        service = WebhookScheduler()
        _overrides["webhook_scheduler_singleton"] = service
    return service


def set_webhook_scheduler_provider(scheduler: Any) -> None:
    """Установить override планировщика webhook'ов (test-инжекция).

    Args:
        scheduler: Экземпляр планировщика (или ``None`` — сброс).

    """
    if scheduler is None:
        _overrides.pop("webhook_scheduler", None)
        _overrides.pop("webhook_scheduler_singleton", None)
        return
    _overrides["webhook_scheduler"] = scheduler
