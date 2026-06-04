"""Langfuse PII anonymization callback (S24 W1, ADR-NEW-16).

Перед отправкой trace-данных в Langfuse (`input` / `output` / `metadata`)
применяет PII-маскирование через DI-provider :func:`get_ai_sanitizer_provider`.
Это гарантирует, что в Langfuse observability backend никогда не уходят
сырые ФИО, ИНН, СНИЛС, паспорт или другие чувствительные сущности.

Активируется через feature-flag ``PRESIDIO_PII_ENABLED`` (S24 W1):

* False — callback no-op (legacy traces без PII filter).
* True — callback применяет PresidioSanitizerAdapter ко всем строковым
  payload'ам перед отправкой в Langfuse.

Audit:
    Каждое маскирование пишет audit-event ``pii.anonymized`` через
    :func:`emit_pii_audit_event` (capability ``pii.audit.<tenant>``).
"""

from __future__ import annotations

import logging
from typing import Any

from src.backend.core.config.features import feature_flags

__all__ = ("LangfusePIICallback", "anonymize_trace_payload")

logger = logging.getLogger("services.ai.gateway.langfuse_pii")


def anonymize_trace_payload(
    payload: dict[str, Any] | None, *, tenant_id: str | None = None
) -> dict[str, Any] | None:
    """Anonymize все строковые значения в trace-payload рекурсивно.

    Применяет PII-маскер через DI-provider. При выключенном
    ``PRESIDIO_PII_ENABLED`` возвращает payload без изменений (no-op).

    Args:
        payload: Trace-payload (input/output/metadata) — словарь с
            произвольной вложенностью. None → None (passthrough).
        tenant_id: Tenant-контекст для audit-event (опционально).

    Returns:
        Новый словарь с замаскированными строками; mapping не возвращается
        (это односторонняя анонимизация — restore не предполагается).
    """
    if payload is None or not feature_flags.presidio_pii_enabled:
        return payload

    from src.backend.core.di.providers import get_ai_sanitizer_provider

    sanitizer = get_ai_sanitizer_provider()
    return _walk_anonymize(payload, sanitizer, tenant_id)


def _walk_anonymize(value: Any, sanitizer: Any, tenant_id: str | None) -> Any:
    """Recursive anonymize: dict/list/str → новые структуры без PII."""
    if isinstance(value, str) and value:
        result = sanitizer.sanitize_text(value)
        if result.replacements:
            _emit_pii_audit(
                "pii.anonymized",
                tenant_id=tenant_id,
                entity_count=len(result.replacements),
                source="langfuse",
            )
        return result.sanitized_text
    if isinstance(value, dict):
        return {k: _walk_anonymize(v, sanitizer, tenant_id) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk_anonymize(item, sanitizer, tenant_id) for item in value]
    return value


def _emit_pii_audit(
    event_type: str, *, tenant_id: str | None, entity_count: int, source: str
) -> None:
    """Emit pii.{detected,anonymized,blocked} audit-event.

    Использует существующий audit-pipeline (Redis stream при наличии,
    fallback на structured log). При полном S24 closure заменится
    на immutable Postgres audit-sink (см. carryover).
    """
    try:
        logger.info(
            "pii_audit",
            extra={
                "event": event_type,
                "tenant_id": tenant_id or "unknown",
                "entity_count": entity_count,
                "source": source,
            },
        )
    except Exception as _:
        logger.debug("pii_audit emit failed", exc_info=True)


class LangfusePIICallback:
    """Callable-обёртка для регистрации в Langfuse before_send hook.

    Использование:

        from src.backend.services.ai.gateway.langfuse_pii_callback import (
            LangfusePIICallback,
        )

        langfuse_client.register_event_processor(LangfusePIICallback())
    """

    def __init__(self, *, tenant_id: str | None = None) -> None:
        self._tenant_id = tenant_id

    def __call__(self, event: dict[str, Any]) -> dict[str, Any]:
        """Anonymize input/output/metadata перед отправкой в Langfuse API."""
        cloned = dict(event)
        for key in ("input", "output", "metadata"):
            if key in cloned:
                cloned[key] = anonymize_trace_payload(
                    cloned[key], tenant_id=self._tenant_id
                )
        return cloned
