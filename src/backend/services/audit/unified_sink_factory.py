"""UnifiedAISink factory (layer-correct placement).

Находится в ``services/`` т.к.:
1. Импортирует ``AuditService`` из ``services.audit.audit_service``
2. Импортирует ``LangFuseCallbackV3`` из ``services.ai.gateway``

Этот модуль — единая точка создания ``UnifiedAISink`` с backends.
Регистрирует ``_emit_ai_invocation_event`` в ``core/audit/sinks/ai_unified_sink``
при первом импорте, после чего ``core/`` не нужен прямой импорт из ``services/``.
"""

from __future__ import annotations

import logging

from src.backend.core.audit.sinks.ai_unified_sink import (
    UnifiedAISink,
    register_emit_ai_invocation_event,
)

logger = logging.getLogger(__name__)


def _create_emit_ai_invocation_event() -> None:
    """Создаёт и регистрирует emit-функцию через lazy-инициализацию singleton."""
    from src.backend.core.audit.schema.ai_invocation import AIInvocationEvent

    _unified_sink: UnifiedAISink | None = None

    def get_unified_sink() -> UnifiedAISink:
        nonlocal _unified_sink
        if _unified_sink is not None:
            return _unified_sink

        try:
            from src.backend.core.config.features import feature_flags

            enabled = bool(feature_flags.ai_audit_unified_enabled)
        except Exception:  # noqa: BLE001
            enabled = False

        if enabled:
            try:
                from src.backend.services.audit.audit_service import (
                    get_unified_audit_service,
                )

                audit = get_unified_audit_service()
                langfuse = None
                try:
                    from src.backend.services.ai.gateway.langfuse_callback_v3 import (
                        LangFuseCallbackV3,
                    )

                    langfuse = LangFuseCallbackV3()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("LangFuseCallbackV3 init failed: %s", exc)

                _unified_sink = UnifiedAISink(
                    audit_service=audit, langfuse_callback=langfuse, enabled=True
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("UnifiedAISink: init failed: %s", exc)
                _unified_sink = UnifiedAISink(enabled=False)
        else:
            _unified_sink = UnifiedAISink(enabled=False)

        return _unified_sink

    def emit_ai_invocation(event: AIInvocationEvent) -> None:
        sink = get_unified_sink()
        try:
            from src.backend.core.utils.task_registry import get_task_registry

            registry = get_task_registry()
            registry.create_task(
                sink.emit_event(event), name=f"audit.emit.{event.event_type.value}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("emit_ai_invocation_event: failed to schedule: %s", exc)

    # Регистрируем в core/ — после этого core/ai/gateway может вызывать
    # emit через core/ без прямого импорта из services/
    register_emit_ai_invocation_event(emit_ai_invocation)


# Регистрация при импорте модуля
_create_emit_ai_invocation_event()

__all__ = ()
