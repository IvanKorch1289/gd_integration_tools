"""IP-restriction DSL mixin для RouteBuilder.

Регистрирует per-route IP-правила в едином ``IPRestrictionStore``;
проверка выполняется на уровне ASGI ``IPRestrictionMiddleware``.
"""

from __future__ import annotations

from typing import Self

from src.backend.core.security.ip_restriction_store import get_ip_restriction_store
from src.backend.dsl.builders.base._protocol import _RouteBuilderProtocol


class IPRestrictionMixin(_RouteBuilderProtocol):
    """Per-route IP-ограничения через RouteBuilder."""

    __slots__ = ()

    def ip_restriction(
        self,
        allowed_ips: set[str] | list[str] | tuple[str, ...],
        *,
        path_pattern: str | None = None,
        enabled: bool = True,
    ) -> Self:
        """Ограничивает доступ к маршруту по IP/CIDR.

        Args:
            allowed_ips: Список разрешённых IP или CIDR.
            path_pattern: Glob-паттерн пути. Если не указан — используется
                ``/api/v1/auto/{route_id}`` (авто-роут action).
            enabled: Включено ли правило.

        Returns:
            RouteBuilder для fluent-chain.

        Example::

            RouteBuilder.from_("payments.import", source="timer:60s")
            .ip_restriction(["10.0.0.0/8", "127.0.0.1"])
            .dispatch_action("payments.process")
            .build()
        """
        pattern = path_pattern or f"/api/v1/auto/{self.route_id}"
        get_ip_restriction_store().set_route_rule(
            path_pattern=pattern, allowed_ips=allowed_ips, enabled=enabled
        )
        return self
