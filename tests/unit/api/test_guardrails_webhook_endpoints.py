"""ADR-0432 — эндпоинты метрик guardrails и планировщика webhook'ов.

Контекст
--------
В портале были панели «Guardrails-метрики» и «Запланированные webhooks», но
серверных эндпоинтов не было (404). Сервисы ``GuardrailsMetricsService`` и
``WebhookScheduler`` существовали, однако не были подключены к DI.

Проверяется здесь:

* ``GET /admin/guardrails-metrics`` отдаёт агрегаты сервиса;
* ``POST /admin/guardrails-metrics/{tenant}/false-positive`` — 404 без
  метрик, 200 с обновлёнными метриками;
* ``GET /webhooks/scheduled`` отдаёт список планировщика;
* ``POST /webhook/schedule`` отклоняет SSRF-небезопасный URL (400) и
  планирует безопасный (201).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from src.backend.core.di.providers import guardrails as guardrails_provider
from src.backend.core.di.providers import webhooks as webhooks_provider

pytestmark = pytest.mark.unit


class _FakeMetrics:
    """Метрики одного тенанта (совместимый с ``GuardrailMetrics.to_dict``)."""

    def __init__(self, total: int = 10, false_positives: int = 1) -> None:
        self.total = total
        self.false_positives = false_positives

    def to_dict(self) -> dict[str, Any]:
        """Представление метрик для API."""
        return {
            "tenant_id": "tenant-a",
            "total": self.total,
            "false_positives": self.false_positives,
        }


class _FakeMetricsService:
    """Заглушка ``GuardrailsMetricsService``."""

    def __init__(self, metrics: list[_FakeMetrics] | None = None) -> None:
        self._metrics = metrics or []
        self.marked: list[tuple[str, int]] = []

    async def list_all(self) -> list[_FakeMetrics]:
        """Список метрик по тенантам."""
        return list(self._metrics)

    async def snapshot(self, tenant_id: str) -> _FakeMetrics:
        """Метрики тенанта (пустые — если тенанта нет)."""
        for item in self._metrics:
            if item.to_dict()["tenant_id"] == tenant_id:
                return item
        return _FakeMetrics(total=0)

    async def mark_false_positive(self, *, tenant_id: str, count: int = 1) -> None:
        """Отметить false-positive."""
        self.marked.append((tenant_id, count))


class _FakeScheduler:
    """Заглушка ``WebhookScheduler``."""

    def __init__(self) -> None:
        self.scheduled: list[dict[str, Any]] = []

    async def list_scheduled(self, *, tenant_id: str = "") -> list[dict[str, Any]]:
        """Список запланированных webhook'ов."""
        return [
            {"id": "abc", "url": "https://example.test/hook", "tenant_id": tenant_id}
        ]

    async def schedule(
        self,
        url: str,
        payload: dict[str, Any],
        cron: str | None = None,
        delay_seconds: int | None = None,
        headers: dict[str, str] | None = None,
        *,
        tenant_id: str = "",
    ) -> str:
        """Запланировать webhook."""
        self.scheduled.append(
            {
                "url": url,
                "payload": payload,
                "cron": cron,
                "delay_seconds": delay_seconds,
                "tenant_id": tenant_id,
            }
        )
        return "sched-1"


@pytest.mark.asyncio
async def test_list_guardrails_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET guardrails-метрик отдаёт агрегаты сервиса."""
    from src.backend.entrypoints.api.v1.endpoints.admin_guardrails import (
        list_guardrails_metrics,
    )

    service = _FakeMetricsService([_FakeMetrics()])
    monkeypatch.setattr(
        guardrails_provider, "get_guardrails_metrics_service_provider", lambda: service
    )

    items = await list_guardrails_metrics()
    assert items[0]["tenant_id"] == "tenant-a"
    assert items[0]["total"] == 10


@pytest.mark.asyncio
async def test_mark_false_positive_updates(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST false-positive обновляет метрики."""
    from src.backend.entrypoints.api.v1.endpoints.admin_guardrails import (
        mark_guardrails_false_positive,
    )

    service = _FakeMetricsService([_FakeMetrics()])
    monkeypatch.setattr(
        guardrails_provider, "get_guardrails_metrics_service_provider", lambda: service
    )

    result = await mark_guardrails_false_positive("tenant-a", 2)
    assert service.marked == [("tenant-a", 2)]
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_mark_false_positive_404_without_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без метрик тенанта — 404 (нет чего отмечать)."""
    from src.backend.entrypoints.api.v1.endpoints.admin_guardrails import (
        mark_guardrails_false_positive,
    )

    service = _FakeMetricsService([])
    monkeypatch.setattr(
        guardrails_provider, "get_guardrails_metrics_service_provider", lambda: service
    )

    with pytest.raises(HTTPException) as exc_info:
        await mark_guardrails_false_positive("tenant-unknown", 1)
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_list_scheduled_webhooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET webhooks/scheduled отдаёт список планировщика."""
    from src.backend.entrypoints.api.v1.endpoints.webhook_scheduler import (
        list_scheduled_webhooks,
    )

    scheduler = _FakeScheduler()
    monkeypatch.setattr(
        webhooks_provider, "get_webhook_scheduler_provider", lambda: scheduler
    )

    items = await list_scheduled_webhooks(tenant_id="tenant-a")
    assert items[0]["id"] == "abc"


def _auth(tenant_id: str = "tenant-a"):
    """Auth-контекст admin-операции."""
    from src.backend.core.auth import AuthContext, AuthMethod

    return AuthContext(
        method=AuthMethod.JWT, principal="ops", metadata={"tenant_id": tenant_id}
    )


@pytest.mark.asyncio
async def test_schedule_webhook_rejects_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Внутренний URL отклоняется SSRF-guard'ом (400)."""
    from src.backend.entrypoints.api.v1.endpoints.webhook_scheduler import (
        WebhookScheduleRequest,
        schedule_webhook,
    )

    scheduler = _FakeScheduler()
    monkeypatch.setattr(
        webhooks_provider, "get_webhook_scheduler_provider", lambda: scheduler
    )

    request = WebhookScheduleRequest(url="http://127.0.0.1:9000/internal")
    with pytest.raises(HTTPException) as exc_info:
        await schedule_webhook(request, auth=_auth(), tenant_id="tenant-a")
    assert exc_info.value.status_code == 400
    assert not scheduler.scheduled


@pytest.mark.asyncio
async def test_schedule_webhook_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """Безопасный URL планируется."""
    from src.backend.core.auth import AuthContext, AuthMethod
    from src.backend.entrypoints.api.v1.endpoints.webhook_scheduler import (
        WebhookScheduleRequest,
        schedule_webhook,
    )

    scheduler = _FakeScheduler()
    monkeypatch.setattr(
        webhooks_provider, "get_webhook_scheduler_provider", lambda: scheduler
    )

    request = WebhookScheduleRequest(url="https://example.test/hook")
    auth = AuthContext(
        method=AuthMethod.JWT, principal="ops", metadata={"tenant_id": "tenant-a"}
    )
    result = await schedule_webhook(request, auth=auth, tenant_id="tenant-a")
    assert result["schedule_id"] == "sched-1"
    assert scheduler.scheduled[0]["url"] == "https://example.test/hook"


@pytest.mark.asyncio
async def test_schedule_webhook_rejects_foreign_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Чужой tenant_id → 403 (ADR-0345: tenant-скоупинг)."""
    from src.backend.core.auth import AuthContext, AuthMethod
    from src.backend.entrypoints.api.v1.endpoints.webhook_scheduler import (
        WebhookScheduleRequest,
        schedule_webhook,
    )

    scheduler = _FakeScheduler()
    monkeypatch.setattr(
        webhooks_provider, "get_webhook_scheduler_provider", lambda: scheduler
    )

    request = WebhookScheduleRequest(url="https://example.test/hook")
    auth = AuthContext(
        method=AuthMethod.JWT, principal="ops", metadata={"tenant_id": "tenant-a"}
    )
    with pytest.raises(HTTPException) as exc_info:
        await schedule_webhook(request, auth=auth, tenant_id="tenant-b")
    assert exc_info.value.status_code == 403
    assert not scheduler.scheduled


@pytest.mark.asyncio
async def test_schedule_webhook_uses_caller_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без явного tenant_id берётся тенант вызывающего."""
    from src.backend.core.auth import AuthContext, AuthMethod
    from src.backend.entrypoints.api.v1.endpoints.webhook_scheduler import (
        WebhookScheduleRequest,
        schedule_webhook,
    )

    scheduler = _FakeScheduler()
    monkeypatch.setattr(
        webhooks_provider, "get_webhook_scheduler_provider", lambda: scheduler
    )

    request = WebhookScheduleRequest(url="https://example.test/hook")
    auth = AuthContext(
        method=AuthMethod.JWT, principal="ops", metadata={"tenant_id": "tenant-a"}
    )
    await schedule_webhook(request, auth=auth, tenant_id="")
    assert scheduler.scheduled[0]["tenant_id"] == "tenant-a"
