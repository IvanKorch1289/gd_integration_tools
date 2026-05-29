"""Unified ``AuditService`` facade (Sprint 16 Wave 8, CP-20 / B-7 partial).

Тонкий фасад над существующим :class:`ClickHouseAuditService` с
универсальной сигнатурой :meth:`AuditService.emit`. Автоматически
извлекает ``correlation_id`` / ``tenant_id`` из contextvars
``infrastructure.observability.correlation``.

Цель: единая точка эмита для всех source'ов (HTTP middleware, AI workspace,
WAF outbound, capability gate, DSL pipeline, feature-flag toggle).
Существующие legacy ``_emit_audit``/``log_capability_event`` callsite'ы
постепенно переходят на этот фасад без breaking-changes — оригинальные
inline-логи остаются как backward-compat.

Контракт ``emit``::

    await audit_service.emit(
        event="feature.toggled",
        actor="admin:alice",
        resource="feature_flag/ai_workspace_ttl_cleanup",
        action="toggle",
        outcome="success",
        # correlation_id / tenant_id берутся из contextvar, можно override.
        details={"old": False, "new": True},
    )

Не зависит от :mod:`fastapi` или request-обвязки — работает в любом
async-контексте (lifespan/workflow activity/CLI).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from src.backend.services.audit.clickhouse_audit_service import (
        ClickHouseAuditService,
    )

__all__ = ("AuditService", "get_unified_audit_service")

_logger = logging.getLogger("services.audit.unified")

_AuditSeverity = Literal["info", "warning", "error"]


class AuditService:
    """Унифицированный фасад emit над :class:`ClickHouseAuditService`.

    Args:
        clickhouse_service: Опц. underlying ClickHouse-сервис (DI). По
            умолчанию резолвится через :func:`get_audit_service`.

    Не вводит новой таблицы — пишет в существующую ``audit_events`` поверх
    тех же колонок (event_type, tenant_id, user_id, payload, severity).
    Расширенные поля (actor/resource/action/outcome) сериализуются в
    ``payload`` JSON для backward compat со schema.
    """

    __slots__ = ("_backend",)

    def __init__(
        self, clickhouse_service: "ClickHouseAuditService | None" = None
    ) -> None:
        self._backend = clickhouse_service

    async def emit(
        self,
        *,
        event: str,
        actor: str | None = None,
        resource: str | None = None,
        action: str | None = None,
        outcome: Literal["success", "failure", "denied"] = "success",
        severity: _AuditSeverity = "info",
        correlation_id: str | None = None,
        tenant_id: str | None = None,
        route_name: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Универсальный emit audit-события.

        Поля контракта (Sprint 16 Wave 8):
            event: Машиночитаемый тип ("feature.toggled", "waf.denied",
                "capability.granted", "auth.login").
            actor: Идентификатор инициатора (``user:<id>``, ``plugin:<name>``,
                ``system``). Опц., если очевиден из ``user_id``.
            resource: Что затронуто (``feature_flag/<name>``,
                ``capability:net.outbound:api.example.com``, ``user/123``).
            action: Глагол ("toggle", "scan", "deny", "create").
            outcome: ``success`` / ``failure`` / ``denied`` — финальное
                состояние операции.
            severity: ClickHouse severity (info/warning/error).
            correlation_id: Опц. override. Если ``None`` — берётся из
                contextvar ``infrastructure.observability.correlation``.
            tenant_id: Опц. override (аналогично correlation_id).
            route_name: HTTP path / workflow_id / иной namespace.
            details: Произвольный словарь специфики события.

        Поведение:
            * Никогда не raise (audit не должен ломать бизнес-логику).
            * При ClickHouse недоступен — лог WARNING + drop.
            * При feature_flag ``audit_clickhouse_enabled=False`` — no-op
              на стороне backend'а (стандартное поведение
              :class:`ClickHouseAuditService`).
        """
        if correlation_id is None:
            correlation_id = _get_correlation_id_safe()
        if tenant_id is None:
            tenant_id = _get_tenant_id_safe()

        payload = {
            "actor": actor,
            "resource": resource,
            "action": action,
            "outcome": outcome,
            "correlation_id": correlation_id or None,
        }
        if details:
            payload["details"] = details

        try:
            backend = self._resolve_backend()
            from src.backend.services.audit.clickhouse_audit_service import (
                make_audit_event,
            )

            audit_event = make_audit_event(
                event_type=event,
                payload=payload,
                severity=severity,
                tenant_id=tenant_id,
                user_id=actor if actor and actor.startswith("user:") else None,
                route_name=route_name,
            )
            await backend.emit(audit_event)
        except Exception as exc:  # noqa: BLE001
            _logger.warning(
                "audit.unified.emit_failed",
                extra={
                    "event": event,
                    "actor": actor,
                    "outcome": outcome,
                    "error": repr(exc),
                },
            )

    def _resolve_backend(self) -> "ClickHouseAuditService":
        """Lazy-резолв backend'а — singleton ClickHouseAuditService."""
        if self._backend is None:
            from src.backend.services.audit.clickhouse_audit_service import (
                get_audit_service,
            )

            self._backend = get_audit_service()
        return self._backend


def _get_correlation_id_safe() -> str | None:
    """Возвращает correlation_id из contextvar или ``None`` при отсутствии."""
    try:
        from src.backend.infrastructure.observability.correlation import (
            get_correlation_id,
        )

        value = get_correlation_id()
        return value or None
    except Exception as _:  # noqa: BLE001
        return None


def _get_tenant_id_safe() -> str | None:
    """Возвращает tenant_id из ``TenantContext.current`` или None."""
    try:
        from src.backend.core.tenancy import current_tenant

        ctx = current_tenant()
        return ctx.tenant_id if ctx is not None else None
    except Exception as _:  # noqa: BLE001
        return None


_unified_service: AuditService | None = None


def get_unified_audit_service() -> AuditService:
    """Singleton-фабрика :class:`AuditService`."""
    global _unified_service
    if _unified_service is None:
        _unified_service = AuditService()
    return _unified_service
