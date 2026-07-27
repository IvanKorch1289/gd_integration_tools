"""IntegrationFacade — единая точка входа для extensions к sink/source.

S203 W4: закрывает gap Master Prompt §3.3 — у Integration не было facade.
Extension'ы раньше импортировали ``infrastructure.sinks.factory.build_sink``
напрямую. Теперь — единый ``IntegrationFacade`` с capability-gating.

Использование::

    from src.backend.services.integrations.facade import get_integration_facade

    facade = get_integration_facade()
    await facade.send_to_sink("alerts.http", {"msg": "hi"})
    result = await facade.check_sink_health("alerts.http")

Capability contract: ``sink.send.<kind>`` (e.g., ``sink.send.http``,
``sink.send.mq``). Автоматически попадает в ``AIPolicySpec.tools``
для агентов через AgentSecurityFramework.

Ponytail: thin wrapper над SinkRegistry/SourceRegistry/AuthorizationFacade.
Никакой новой логики — только re-export + audit + capability gate.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.core.interfaces.sink import SinkResult
from src.backend.core.logging import get_logger
from src.backend.core.security.capabilities.errors import CapabilityDeniedError
from src.backend.services.sources.registry import (
    SinkRegistry,
    SourceRegistry,
    get_sink_registry,
    get_source_registry,
)

__all__ = ("IntegrationFacade", "get_integration_facade")

_logger = get_logger("services.integrations.facade")


class IntegrationFacade:
    """S203 W4: единая точка доступа к Sink/Source для extensions.

    Methods:
        send_to_sink: capability-gated отправка payload через зарегистрированный Sink.
        check_sink_health: ping одного Sink.
        check_source_health: ping одного Source.
        list_sinks / list_sources: introspection.
    """

    def __init__(self) -> None:
        self._sinks: SinkRegistry | None = None
        self._sources: SourceRegistry | None = None

    @property
    def sinks(self) -> SinkRegistry:
        """Метод sinks (см. signature)."""
        if self._sinks is None:
            self._sinks = get_sink_registry()
        return self._sinks

    @property
    def sources(self) -> SourceRegistry:
        """Метод sources (см. signature)."""
        if self._sources is None:
            self._sources = get_source_registry()
        return self._sources

    async def _check_capability(
        self, capability: str, *, context: dict[str, Any] | None = None
    ) -> bool:
        """S203 W4: проверка capability через AuthorizationFacade.

        Args:
            capability: Полное имя capability (e.g., ``"sink.send.http"``).
            context: Дополнительный контекст (tenant_id, principal).

        Returns:
            True если allowed, False иначе.
        """
        try:
            from src.backend.services.authorization.facade import (
                get_authorization_facade,
            )

            decision = await get_authorization_facade().authorize(
                required_capability=capability,
                context=context or {},
            )
            return bool(decision.allowed)
        except Exception as exc:
            # Fail-closed: если authz слой недоступен, запрещаем доступ.
            _logger.warning(
                "authz unavailable for capability=%s, denying: %s", capability, exc
            )
            return False

    async def send_to_sink(
        self,
        sink_id: str,
        payload: Any,
        *,
        tenant_id: str | None = None,
        principal: str | None = None,
    ) -> SinkResult:
        """Отправить ``payload`` через зарегистрированный Sink с capability gate.

        Args:
            sink_id: Идентификатор Sink (зарегистрированный через SinkRegistry).
            payload: Полезная нагрузка (dict/bytes/str — backend знает).
            tenant_id: Tenant ID для authz context.
            principal: Principal identity (для audit).

        Returns:
            ``SinkResult`` с ``ok`` и метаданными доставки.

        Raises:
            KeyError: Sink не найден.
            CapabilityDeniedError: Нет capability ``sink.send.<kind>``.
        """
        sink = self.sinks.get(sink_id)  # KeyError если не найден
        capability = f"sink.send.{sink.kind.value}"

        if not await self._check_capability(
            capability,
            context={"tenant_id": tenant_id, "principal": principal},
        ):
            raise CapabilityDeniedError(
                capability=capability,
                resource=sink_id,
                subject=principal or "unknown",
            )

        _logger.info(
            "integration.send_to_sink sink_id=%s kind=%s principal=%s",
            sink_id,
            sink.kind.value,
            principal,
        )
        return await sink.send(payload)

    async def check_sink_health(
        self, sink_id: str
    ) -> dict[str, Any]:
        """Ping одного Sink. Не требует capability (read-only).

        Args:
            sink_id: Идентификатор Sink.

        Returns:
            Dict с ``status``, ``latency_ms``, ``error``.

        Raises:
            KeyError: Sink не найден.
        """
        sink = self.sinks.get(sink_id)
        result = await sink.health(mode="fast")
        if hasattr(result, "status"):
            return {
                "status": result.status,
                "latency_ms": result.latency_ms,
                "error": result.error,
            }
        if isinstance(result, dict):
            return result
        return {"status": "ok"}

    async def check_source_health(
        self, source_id: str
    ) -> dict[str, Any]:
        """Ping одного Source. Не требует capability (read-only).

        Args:
            source_id: Идентификатор Source.

        Returns:
            Dict с ``status``, ``latency_ms``, ``error``.

        Raises:
            KeyError: Source не найден.
        """
        source = self.sources.get(source_id)
        result = await source.health(mode="fast")
        if hasattr(result, "status"):
            return {
                "status": result.status,
                "latency_ms": result.latency_ms,
                "error": result.error,
            }
        if isinstance(result, dict):
            return result
        return {"status": "ok"}

    def list_sinks(self) -> tuple[str, ...]:
        """Все зарегистрированные sink_id (для DSL discoverability)."""
        return tuple(s.sink_id for s in self.sinks.all())

    def list_sources(self) -> tuple[str, ...]:
        """Все зарегистрированные source_id (для DSL discoverability)."""
        return tuple(s.source_id for s in self.sources.all())


@app_state_singleton("integration_facade", factory=IntegrationFacade)
def get_integration_facade() -> IntegrationFacade:
    """S203 W4: lazy singleton-аксессор :class:`IntegrationFacade`.

    Lazy-инициализация через ``@app_state_singleton`` — фабрика создаёт
    пустой facade, sinks/sources подтягиваются через свойства при первом
    обращении.
    """
    raise RuntimeError("unreachable — фабрика создаёт пустой facade")
