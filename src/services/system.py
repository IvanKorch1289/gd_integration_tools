"""SystemService — unified system introspection + management.

Consolidates TechService + AdminService into single API surface.
Both services provide overlapping system-level operations:
- Health checks (tech.check_*, admin.get_config)
- Configuration (admin.*)
- Feature flags (admin.toggle_feature_flag)
- Service introspection (admin.list_services, admin.list_actions)
- Email/notification (tech.send_email)

Не заменяет существующие Tech/Admin, а предоставляет unified facade.
Старые методы остаются для backward compatibility.

Multi-instance safety:
- Feature flags → Redis-backed runtime_state (уже существует)
- Cache operations → Redis (centralized)
- Health checks → per-instance (Prometheus aggregates)
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("SystemService", "get_system_service")

logger = logging.getLogger("services.system")


class SystemService:
    """Unified система + admin operations — фасад над Tech + Admin.

    Делегирует в существующие TechService/AdminService + HealthAggregator.
    Позволяет единым API видеть всё системное состояние.
    """

    def __init__(self) -> None:
        self._tech: Any = None
        self._admin: Any = None

    @property
    def tech(self) -> Any:
        if self._tech is None:
            from app.services.tech import get_tech_service
            self._tech = get_tech_service()
        return self._tech

    @property
    def admin(self) -> Any:
        if self._admin is None:
            from app.services.admin import get_admin_service
            self._admin = get_admin_service()
        return self._admin

    # ── Health / Status ─────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        """Unified health check через HealthAggregator."""
        try:
            from app.infrastructure.application.health_aggregator import get_health_aggregator
            return await get_health_aggregator().check_all()
        except ImportError:
            return await self.tech.check_all_services()

    async def component_health(self, name: str) -> dict[str, Any]:
        """Health одного компонента."""
        from app.infrastructure.application.health_aggregator import get_health_aggregator
        return await get_health_aggregator().check_single(name)

    # ── Configuration ───────────────────────────────────────

    async def get_config(self) -> dict[str, Any]:
        """Возвращает общую конфигурацию приложения."""
        return await self.admin.get_config()

    async def list_feature_flags(self) -> dict[str, Any]:
        """Список всех feature flags с текущим состоянием."""
        return await self.admin.list_feature_flags()

    async def toggle_feature_flag(self, flag: str, enabled: bool) -> dict[str, Any]:
        """Включить/выключить feature flag (Redis-backed, cross-instance)."""
        return await self.admin.toggle_feature_flag(flag=flag, enabled=enabled)

    # ── Introspection ───────────────────────────────────────

    async def list_services(self) -> list[dict[str, Any]]:
        """Список всех зарегистрированных сервисов."""
        return await self.admin.list_services()

    async def list_actions(self) -> list[str]:
        """Список всех action handlers."""
        return await self.admin.list_actions()

    async def list_routes(self) -> list[dict[str, Any]]:
        """Список всех DSL маршрутов."""
        return await self.admin.list_routes()

    # ── Cache Management (Redis) ────────────────────────────

    async def list_cache_keys(self, pattern: str = "*") -> list[str]:
        return await self.admin.list_cache_keys(pattern=pattern)

    async def invalidate_cache(self, pattern: str = "*") -> dict[str, Any]:
        """Invalidate cache by pattern (Redis SCAN + DEL, multi-instance safe)."""
        return await self.admin.invalidate_cache(pattern=pattern)

    # ── SLO Metrics ─────────────────────────────────────────

    async def slo_report(self) -> dict[str, Any]:
        """P50/P95/P99 по всем DSL маршрутам."""
        try:
            from app.infrastructure.application.slo_tracker import get_slo_tracker
            return get_slo_tracker().get_report()
        except ImportError:
            return {}

    # ── Notifications ───────────────────────────────────────

    async def send_email(self, **kwargs: Any) -> dict[str, Any]:
        """Отправка email (делегирует в TechService)."""
        return await self.tech.send_email(**kwargs)


_instance: SystemService | None = None


def get_system_service() -> SystemService:
    global _instance
    if _instance is None:
        _instance = SystemService()
    return _instance
