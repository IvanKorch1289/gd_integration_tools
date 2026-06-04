"""WAF wiring (Wave 1.4 / S1): глобальный :class:`WafPolicy` + фабрика
:class:`OutboundHttpClient` с capability-checked + audit-callback.

Подключается в lifespan/composition root после :func:`register_secrets_backend`.
Все ``:external`` исходящие HTTP идут через зарегистрированный
``OutboundHttpClient`` (см. ADR R-V15-5).

Audit-callback пишет события через структурированный logger (channel
``waf.audit``); ImmutableAuditStore используется только для критичных
DB-аудитов и не подходит для high-throughput WAF-метрик.
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.net.outbound_http import OutboundHttpClient
from src.backend.core.net.waf import WafPolicy
from src.backend.core.svcs_registry import has_service, register_factory

__all__ = ("register_outbound_http_client", "register_waf_policy", "waf_audit_callback")

_logger = logging.getLogger("waf.audit")


def waf_audit_callback(event: dict[str, Any]) -> None:
    """Структурированный audit-event WAF (granted/denied)."""
    outcome = "granted" if event.get("allowed") else "denied"
    _logger.info(
        "waf.evaluate",
        extra={
            "waf_outcome": outcome,
            "plugin": event.get("plugin"),
            "method": event.get("method"),
            "host": event.get("host"),
            "url": event.get("url"),
            "reason": event.get("reason"),
        },
    )


def _build_waf_policy_from_settings() -> WafPolicy:
    """Сконструировать ``WafPolicy`` из ``waf_settings`` (lazy import).

    Sprint 16 Wave 7 (B-3 finale wiring): подключает ClamAV scanner через
    :func:`build_clamav_scanner_if_enabled` если активирован feature-flag
    ``WAF_CLAMAV_ENABLED``. См. модуль ``infrastructure.antivirus.setup``.
    """
    from src.backend.core.config.waf import waf_settings
    from src.backend.infrastructure.antivirus.setup import (
        build_clamav_scanner_if_enabled,
    )

    return WafPolicy(
        allow_hosts=frozenset(waf_settings.allow_hosts),
        deny_hosts=frozenset(waf_settings.deny_hosts),
        max_payload_bytes=waf_settings.max_payload_bytes or None,
        strict=waf_settings.strict,
        async_payload_scanner=build_clamav_scanner_if_enabled(),
    )


def register_waf_policy() -> None:
    """Зарегистрировать глобальный :class:`WafPolicy` в svcs.

    Идемпотентно: повторный вызов не пересоздаёт фабрику. Policy
    собирается lazy при первом ``get_service(WafPolicy)``.
    """
    if has_service(WafPolicy):
        return
    register_factory(WafPolicy, _build_waf_policy_from_settings)


def _resolve_capability_check() -> Any | None:
    """Найти ``CapabilityGate.check`` в svcs (если зарегистрирован)."""
    try:
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.core.svcs_registry import get_service
    except Exception as _:
        return None
    if not has_service(CapabilityGate):
        return None
    try:
        gate = get_service(CapabilityGate)
    except Exception as _:
        return None
    check = getattr(gate, "check", None)
    return check if callable(check) else None


def register_outbound_http_client(*, plugin: str = "core") -> None:
    """Зарегистрировать ядерный :class:`OutboundHttpClient` в svcs.

    Args:
        plugin: Имя caller'а для audit-event (по-умолчанию ``core``).
            Плагины регистрируют свои клиенты с собственным plugin-name
            через эту же функцию.
    """
    if has_service(OutboundHttpClient):
        return

    def _factory() -> OutboundHttpClient:
        from src.backend.core.svcs_registry import get_service

        policy = (
            get_service(WafPolicy)
            if has_service(WafPolicy)
            else _build_waf_policy_from_settings()
        )
        return OutboundHttpClient(
            policy=policy,
            capability_check=_resolve_capability_check(),
            audit=waf_audit_callback,
            plugin=plugin,
        )

    register_factory(OutboundHttpClient, _factory)
