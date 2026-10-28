"""ADR-0366 — runtime-резолвер capability-гейта для DSL-процессоров.

Зачем этот модуль
-----------------
``BaseProcessor.auth_check`` (ADR-0361) проверял ``required_capability``
через **sync** ``AuthorizationGateway.check``, где allow возможен только
из пустых in-memory policies, а ``CapabilityGate.check`` не вызывался
вовсе → **deny для любой** capability (72 RPA-процессора + ~40 прочих).
Async-ветка ``authorize()`` capability-гейт использовала — пути расходились.

ADR-0366 переносит решение в ``core`` и делает его явным:

* **namespace** решается по кандидатам: ``route_id`` (plugin роута) →
  если capability им объявлена — берётся роут; иначе fallback ``"core"``
  (baseline), который доступен **только** при явном флаге
  ``dsl_capability_core_baseline_enabled`` и только для capability из
  :data:`CORE_CAPABILITIES`; иначе — fail-closed DENY;
* **principal** (кто выполняет действие) **никогда** не используется как
  namespace — иначе анонимный caller открыл бы все capability ядра
  (риск из ADR-0361). Principal используется только для аудита и логов;
* **tenant** обязателен: решение capability-гейта должно быть
  атрибутировано к тенанту (иначе аудит-цепочка разорвана).

Модуль не зависит от DSL-слоя: ``core`` не импортирует ``dsl``
(см. ``tools/check_layers.py``), поэтому резолвер принимает готовый
:class:`CapabilityRequest` и возвращает решение — вызов DSL-процессора
описан в ``dsl/engine/processors/base.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from src.backend.core.logging import get_logger
from src.backend.core.security.capabilities.core_declarations import CORE_CAPABILITIES
from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityNotFoundError,
)
from src.backend.core.security.capabilities.gate import (
    CapabilityGate,
    get_capability_gate,
)

__all__ = (
    "CORE_NAMESPACE",
    "CapabilityDecision",
    "CapabilityRequest",
    "check",
    "resolve_plugin",
)

CORE_NAMESPACE: Final[str] = "core"
"""Namespace ядра — fallback, когда capability не объявлена роутом."""

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    """Запрос на runtime-проверку capability.

    Attributes:
        capability: Имя capability (``"rpa.file.list"``).
        action: Действие (``"read"`` / ``"write"`` / ``"execute"``) — идёт
            в audit-событие.
        plugin: Кандидат namespace'а — plugin/route-id текущего exchange
            (``exchange.meta.route_id``). ``None`` — namespace не задан,
            доступен только core-baseline.
        scope: Запрашиваемый scope (glob). ``None`` — scope не уточнён.
        tenant: Tenant, к которому относится решение. Обязателен: решение
            capability-гейта должно быть атрибутировано к тенанту.

    """

    capability: str
    action: str = "execute"
    plugin: str | None = None
    scope: str | None = None
    tenant: str | None = None


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    """Результат runtime-проверки capability.

    Attributes:
        allowed: ``True`` — доступ разрешён.
        plugin: Резолвнутый namespace (``None`` — namespace не найден).
        reason: Machine-readable причина (``"granted"`` / ``"no_declaration"``
            / ``"tenant_missing"`` / ``"capability_denied"`` /
            ``"unknown_capability"``).
        capability: Имя проверяемой capability.
        tenant: Tenant решения.

    """

    allowed: bool
    plugin: str | None
    reason: str
    capability: str
    tenant: str | None = None


def resolve_plugin(
    request: CapabilityRequest, *, gate: CapabilityGate | None = None
) -> str | None:
    """Резолвит namespace (plugin) для capability-запроса.

    Правило (ADR-0366):

    1. кандидат — ``request.plugin`` (plugin роута); если capability им
       объявлена — namespace'ом становится роут (его собственный scope);
    2. иначе — ``"core"``, но **только** если включён флаг
       ``dsl_capability_core_baseline_enabled`` **и** capability входит в
       :data:`CORE_CAPABILITIES`;
    3. иначе — ``None`` (fail-closed DENY).

    Args:
        request: Запрос на проверку.
        gate: Capability-гейт (по умолчанию — process-wide singleton).

    Returns:
        Имя namespace'а либо ``None``, если ни один кандидат не подходит.

    """
    gate = gate if gate is not None else get_capability_gate()
    if request.plugin and gate.has_declaration(request.plugin, request.capability):
        return request.plugin
    if _core_baseline_enabled() and request.capability in CORE_CAPABILITIES:
        return CORE_NAMESPACE
    return None


def check(
    request: CapabilityRequest,
    *,
    principal: str | None = None,
    gate: CapabilityGate | None = None,
) -> CapabilityDecision:
    """Проверить capability по namespace-правилам ADR-0366.

    Args:
        request: Запрос на проверку.
        principal: Кто выполняет действие (для аудита и логов). **Никогда**
            не используется как namespace.
        gate: Capability-гейт (по умолчанию — process-wide singleton).

    Returns:
        :class:`CapabilityDecision` — fail-closed при любой неопределённости.

    """
    gate = gate if gate is not None else get_capability_gate()

    namespace = resolve_plugin(request, gate=gate)
    if namespace is None:
        return _deny(request, "no_declaration", principal=principal)

    if not request.tenant:
        return _deny(request, "tenant_missing", principal=principal, namespace=namespace)

    try:
        gate.check(namespace, request.capability, request.scope)
    except CapabilityNotFoundError:
        return _deny(
            request, "unknown_capability", principal=principal, namespace=namespace
        )
    except CapabilityDeniedError as exc:
        return _deny(
            request,
            "capability_denied",
            principal=principal,
            namespace=namespace,
            declared_scope=exc.declared_scope,
        )
    except Exception as exc:  # pragma: no cover — fail-closed
        _logger.warning(
            "capability_resolver.gate_error: capability=%s namespace=%s error=%s",
            request.capability,
            namespace,
            exc,
        )
        return _deny(request, "gate_error", principal=principal, namespace=namespace)

    _logger.debug(
        "capability_resolver.granted: capability=%s namespace=%s tenant=%s",
        request.capability,
        namespace,
        request.tenant,
    )
    return CapabilityDecision(
        allowed=True,
        plugin=namespace,
        reason="granted",
        capability=request.capability,
        tenant=request.tenant,
    )


def _core_baseline_enabled() -> bool:
    """Feature-flag ``dsl_capability_core_baseline_enabled`` (ADR-0366)."""
    try:
        from src.backend.core.config.features import feature_flags

        return bool(feature_flags.dsl_capability_core_baseline_enabled)
    except Exception as exc:  # pragma: no cover — default-OFF
        _logger.debug("capability_resolver.baseline_flag_unavailable: %s", exc)
        return False


def _deny(
    request: CapabilityRequest,
    reason: str,
    *,
    principal: str | None,
    namespace: str | None = None,
    declared_scope: str | None = None,
) -> CapabilityDecision:
    """Fail-closed DENY: лог + audit-событие с причиной отказа."""
    _logger.warning(
        "capability_resolver.denied: capability=%s namespace=%s reason=%s "
        "tenant=%s principal=%s",
        request.capability,
        namespace or request.plugin,
        reason,
        request.tenant,
        principal,
    )
    _emit_deny_audit(
        request,
        reason=reason,
        namespace=namespace,
        principal=principal,
        declared_scope=declared_scope,
    )
    return CapabilityDecision(
        allowed=False,
        plugin=namespace,
        reason=reason,
        capability=request.capability,
        tenant=request.tenant,
    )


def _emit_deny_audit(
    request: CapabilityRequest,
    *,
    reason: str,
    namespace: str | None,
    principal: str | None,
    declared_scope: str | None,
) -> None:
    """Audit-событие ``capability.check`` с причиной отказа (никогда не raise)."""
    details: dict[str, Any] = {
        "plugin": namespace or request.plugin,
        "principal": principal,
        "capability": request.capability,
        "requested_scope": request.scope,
        "declared_scope": declared_scope,
        "reason": reason,
    }
    if request.tenant is not None:
        details["tenant"] = request.tenant
    try:
        from src.backend.core.audit.facade import emit_audit

        emit_audit(
            event="capability.check",
            actor=principal or namespace or "system",
            resource=request.capability,
            action=request.action,
            outcome="denied",
            details=details,
        )
    except Exception as exc:  # pragma: no cover — аудит не должен ломать гейт
        _logger.debug("capability_resolver.audit_failed: %s", exc)
