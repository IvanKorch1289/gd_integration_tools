"""AuditProcessor (Wave 11) — запись DSL-событий в immutable audit log.

Использует :class:`ImmutableAuditStore` (Wave 5.1, IL-SEC2) — append-only
HMAC-chained лог в Postgres-таблице ``audit_log_immutable``. Каждое событие
получает hash, связанный с предыдущим: tampering детектируется через
``ImmutableAuditStore.verify``.

Использование в YAML::

    - audit:
        action: order.created
        actor_from: properties.user_id
        resource_from: properties.action_result.id
        outcome: success
        metadata_from: properties.action_result
"""

from __future__ import annotations

import logging
from typing import Any

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor
from src.dsl.engine.processors.entity import _resolve

__all__ = ("AuditProcessor",)

_logger = logging.getLogger("dsl.audit")

_VALID_OUTCOMES = frozenset({"success", "failure", "denied", "error"})


class AuditProcessor(BaseProcessor):
    """Записывает событие в immutable audit log.

    Args:
        action: Имя действия (статический). Например ``order.created``.
        action_from: Альтернативно — выражение из exchange.
        actor_from: Выражение, возвращающее ID actor-а.
        actor: Статический actor (приоритет ниже, чем ``actor_from``).
        resource_from: Выражение, возвращающее ID ресурса.
        outcome: ``success`` | ``failure`` | ``denied`` | ``error``.
        outcome_from: Альтернативно — выражение из exchange.
        metadata_from: Выражение, возвращающее dict с метаданными.
        result_property: Имя exchange-property для записи ``event_hash``.
    """

    def __init__(
        self,
        *,
        action: str | None = None,
        action_from: str | None = None,
        actor: str = "system",
        actor_from: str | None = None,
        resource_from: str | None = None,
        outcome: str = "success",
        outcome_from: str | None = None,
        metadata_from: str | None = None,
        tenant_id_from: str | None = None,
        correlation_id_from: str | None = None,
        result_property: str = "audit_event_hash",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"audit:{action or action_from or 'dynamic'}")
        if not action and not action_from:
            raise ValueError("AuditProcessor: укажите action или action_from")
        if outcome not in _VALID_OUTCOMES:
            raise ValueError(
                f"AuditProcessor: outcome={outcome!r} не из {sorted(_VALID_OUTCOMES)}"
            )
        self._action = action
        self._action_from = action_from
        self._actor = actor
        self._actor_from = actor_from
        self._resource_from = resource_from
        self._outcome = outcome
        self._outcome_from = outcome_from
        self._metadata_from = metadata_from
        self._tenant_id_from = tenant_id_from
        self._correlation_id_from = correlation_id_from
        self._result_property = result_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Извлекает поля и пишет событие в ``ImmutableAuditStore``."""
        action = self._action or str(_resolve(exchange, self._action_from) or "")
        if not action:
            exchange.fail("AuditProcessor: пустое action")
            return

        actor = (
            str(_resolve(exchange, self._actor_from))
            if self._actor_from
            else self._actor
        )
        resource = (
            str(_resolve(exchange, self._resource_from))
            if self._resource_from
            else None
        )
        outcome_value = (
            _resolve(exchange, self._outcome_from)
            if self._outcome_from
            else self._outcome
        )
        outcome = str(outcome_value) if outcome_value else self._outcome
        if outcome not in _VALID_OUTCOMES:
            outcome = "error"

        metadata = (
            _resolve(exchange, self._metadata_from) if self._metadata_from else None
        )
        if metadata is not None and not isinstance(metadata, dict):
            metadata = {"value": metadata}

        tenant_id = (
            str(_resolve(exchange, self._tenant_id_from))
            if self._tenant_id_from
            else None
        )
        correlation_id = (
            str(_resolve(exchange, self._correlation_id_from))
            if self._correlation_id_from
            else None
        )

        try:
            store = self._build_store()
            event_hash = await store.append(
                actor=actor,
                action=action,
                resource=resource,
                outcome=outcome,
                metadata=metadata,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
            )
            exchange.set_property(self._result_property, event_hash)
            _logger.debug(
                "Audit: action=%s actor=%s outcome=%s event_hash=%s",
                action,
                actor,
                outcome,
                event_hash,
            )
        except Exception as exc:
            _logger.warning("AuditProcessor: ошибка записи в audit log: %s", exc)
            exchange.set_property(f"{self._result_property}_error", str(exc))

    @staticmethod
    def _build_store() -> Any:
        """Лениво создаёт ``ImmutableAuditStore`` поверх main_session_manager."""
        from src.infrastructure.database.session_manager import main_session_manager
        from src.infrastructure.observability.immutable_audit import ImmutableAuditStore

        return ImmutableAuditStore(session_factory=main_session_manager.create_session)

    def to_spec(self) -> dict:
        """YAML-spec round-trip."""
        spec: dict[str, Any] = {
            "outcome": self._outcome,
            "actor": self._actor,
            "result_property": self._result_property,
        }
        if self._action is not None:
            spec["action"] = self._action
        if self._action_from is not None:
            spec["action_from"] = self._action_from
        if self._actor_from is not None:
            spec["actor_from"] = self._actor_from
        if self._resource_from is not None:
            spec["resource_from"] = self._resource_from
        if self._outcome_from is not None:
            spec["outcome_from"] = self._outcome_from
        if self._metadata_from is not None:
            spec["metadata_from"] = self._metadata_from
        if self._tenant_id_from is not None:
            spec["tenant_id_from"] = self._tenant_id_from
        if self._correlation_id_from is not None:
            spec["correlation_id_from"] = self._correlation_id_from
        return {"audit": spec}
