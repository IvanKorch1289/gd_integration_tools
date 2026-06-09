"""BaseAIProcessor — общий boilerplate для 10 Agent DSL processors (S27 W1-W3).

Назначение
----------
Устраняет дубликат feature-flag check + capability-gate + audit-emit в
каждом процессоре :mod:`dsl.engine.processors.ai`. Наследники переопределяют:

* :meth:`_run` — core-логика (вместо :meth:`process`);
* :attr:`feature_flag_name` — имя flag в :class:`FeatureFlags`;
* :attr:`required_capability` / :meth:`_capability_scope` — capability gate;
* :attr:`audit_event` — имя audit-события (``ai.agent.run`` / ``ai.skill.invoke`` ...).

Контракт
--------
:meth:`process` обрабатывает:

1. Feature-flag check — при ``False`` — pass-through (no-op).
2. Capability check — при denied — raise :class:`CapabilityDeniedError`.
3. Вызов :meth:`_run`.
4. Audit emit (success / failure) — никогда не raise.

См. также
---------
* :class:`BaseProcessor` — родительский ABC из ``processors/base.py``.
* :class:`AIGateway` — для :class:`AgentRunProcessor`.
* docs/adr/0070-agent-dsl-processors.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("BaseAIProcessor",)

_logger = get_logger(__name__)


class BaseAIProcessor(BaseProcessor):
    """Базовый класс для AI-процессоров с feature-flag + capability + audit.

    Class attributes:
        feature_flag_name: Имя flag в :class:`FeatureFlags` (например
            ``"ai_agent_dsl_enabled"``). При ``None`` — flag-check
            пропускается. При flag=False — :meth:`process` no-op.
        required_capability: Имя capability в vocabulary (``"ai.invoke"``,
            ``"skill.invoke"``). При ``None`` — capability-gate
            пропускается.
        audit_event: Имя audit-события (``"ai.agent.run"``,
            ``"ai.pii.mask"``). При ``None`` — audit-emit пропускается.
        side_effect: SIDE_EFFECTING по умолчанию для AI-процессоров
            (внешний LLM / TokenRegistry / Memory backend).

    Lifecycle:
        Наследник реализует :meth:`_run` — core-логику. :meth:`process`
        обрамляет её feature-flag / capability / audit boilerplate'ом.
    """

    feature_flag_name: ClassVar[str | None] = "ai_agent_dsl_enabled"
    required_capability: ClassVar[str | None] = None
    audit_event: ClassVar[str | None] = None
    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING

    def __init__(self, *, name: str | None = None) -> None:
        """Инициализация. ``name`` форвардится в :class:`BaseProcessor`."""
        super().__init__(name=name)

    # ── Abstract: core-логика наследника ──

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Core-логика процессора (переопределить).

        Args:
            exchange: DSL Exchange.
            context: Execution context.

        Raises:
            NotImplementedError: если наследник не переопределил.
        """
        del exchange, context
        raise NotImplementedError(
            f"{type(self).__name__} must override _run(exchange, context)"
        )

    # ── Template-method: feature_flag + capability + audit + _run ──

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Template-method: проверки → :meth:`_run` → audit-emit.

        При выключенном feature_flag — silent no-op (pass-through).
        При denied capability — raise (выходит из process с error в exchange).
        """
        if not self._check_feature_flag():
            _logger.debug(
                "%s: feature_flag %r=False — pass-through",
                self.name,
                self.feature_flag_name,
            )
            return

        scope = self._capability_scope(exchange)
        try:
            self._check_capability(scope=scope)
        except Exception as exc:
            exchange.set_error(f"{self.name}: capability denied ({exc})")
            exchange.stop()
            await self._emit_audit_safe(
                exchange,
                outcome="denied",
                severity="warning",
                extra={"capability": self.required_capability, "scope": scope},
            )
            return

        try:
            await self._run(exchange, context)
        except Exception as exc:
            exchange.set_error(f"{self.name} error: {exc}")
            exchange.stop()
            await self._emit_audit_safe(
                exchange, outcome="failure", severity="error", extra={"error": str(exc)}
            )
            return

        await self._emit_audit_safe(exchange, outcome="success", severity="info")

    # ── Helpers (для наследников) ──

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope для capability-проверки.

        По умолчанию возвращает ``None`` — capability с
        ``scope_required=False`` пройдёт; capability с
        ``scope_required=True`` упадёт denied. Наследник переопределяет
        для динамического scope (например, ``workflow_id`` из properties).
        """
        del exchange
        return None

    def _check_feature_flag(self) -> bool:
        """Проверить feature-flag через :data:`feature_flags`.

        Returns:
            ``True`` если flag не задан или ``flag=True``; ``False`` иначе.
        """
        if self.feature_flag_name is None:
            return True
        try:
            from src.backend.core.config.features import feature_flags

            value = getattr(feature_flags, self.feature_flag_name, None)
            return bool(value)
        except Exception as exc:
            _logger.debug(
                "%s: feature_flag resolve failed (%s) — default OFF", self.name, exc
            )
            return False

    def _check_capability(self, *, scope: str | None) -> None:
        """Capability-gate через DI.

        Args:
            scope: Динамический scope (например ``"credit_check"``
                для capability ``"ai.invoke"``).

        Raises:
            CapabilityDeniedError: если capability не выдана плагину.
        """
        if self.required_capability is None:
            return
        gate = self._resolve_capability_gate()
        if gate is None:
            return
        check = getattr(gate, "check", None)
        if check is None:
            return
        plugin = self._plugin_name()
        try:
            check(plugin, self.required_capability, scope)
        except TypeError:
            check(self.required_capability)

    def _plugin_name(self) -> str:
        """Имя плагина / route'а для capability check.

        В DSL-контексте processor работает в pipeline без явного
        ``plugin``-namespace; возвращаем ``"core"`` (соответствует
        baseline core capabilities).
        """
        return "core"

    @staticmethod
    def _resolve_capability_gate() -> Any | None:
        """Lazy-резолв :class:`CapabilityGate` через DI singleton."""
        try:
            from src.backend.core.security.capabilities.gate import (  # type: ignore[attr-defined]
                get_capability_gate,
            )

            return get_capability_gate()
        except Exception as _:
            return None

    async def _emit_audit_safe(
        self,
        exchange: Exchange[Any],
        *,
        outcome: str,
        severity: str = "info",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Emit audit-event; никогда не raise."""
        if self.audit_event is None:
            return
        audit = self._resolve_audit_service()
        if audit is None:
            return
        details: dict[str, Any] = {"processor": self.name}
        if extra:
            details.update(extra)
        try:
            await audit.emit(
                event=self.audit_event,
                actor=f"tenant:{exchange.meta.tenant_id or 'unknown'}",
                resource=f"dsl_processor:{self.name}",
                action="process",
                outcome=outcome,
                severity=severity,
                correlation_id=exchange.meta.correlation_id,
                tenant_id=exchange.meta.tenant_id,
                route_name=exchange.meta.route_id,
                details=details,
            )
        except Exception as exc:
            _logger.debug("%s: audit emit failed (%s) — drop", self.name, exc)

    @staticmethod
    def _resolve_audit_service() -> Any | None:
        """Lazy-резолв Unified :class:`AuditService` (S17/K3)."""
        try:
            from src.backend.services.audit.audit_service import (
                get_unified_audit_service,
            )

            return get_unified_audit_service()
        except Exception as _:
            return None
