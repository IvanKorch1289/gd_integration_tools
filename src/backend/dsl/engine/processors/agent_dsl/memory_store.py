"""MemoryStoreProcessor — DSL-обёртка :meth:`MemoryProtocol.store` (S27 W3).

Сохраняет произвольное значение в :class:`MemoryProtocol`-backend'е.

YAML контракт::

    steps:
      - memory_store:
          namespace: "acme:credit_chat"
          key_property: meta.exchange_id
          value_property: agent_result.content
          ttl_s: 86400

Capability ``ai.memory.write.<scope>`` обязательна.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("MemoryStoreProcessor",)

_logger = logging.getLogger(__name__)


class MemoryStoreProcessor(BaseAIProcessor):
    """Сохранить запись в :class:`MemoryProtocol`-backend (S27 W3).

    Args:
        namespace: ``"<tenant_id>:<scope>"``. Поддерживает
            ``${tenant_id}`` placeholder.
        key: Опц. статичный ключ записи.
        key_property: Опц. dot-path для динамического ключа
            (``"meta.exchange_id"`` — из exchange.meta;
            ``"body.user_id"``; ``"property:order_id"``).
        value_property: Откуда взять значение для записи. Default
            ``"agent_result"`` (результат :class:`AgentRunProcessor`).
        ttl_s: Опц. TTL в секундах (``86400`` = 1 день).
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "ai.memory.write"
    audit_event: ClassVar[str | None] = "ai.memory.store"
    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING

    def __init__(
        self,
        *,
        namespace: str,
        key: str | None = None,
        key_property: str | None = None,
        value_property: str = "agent_result",
        ttl_s: int | None = None,
        name: str | None = None,
    ) -> None:
        if not namespace:
            raise ValueError("MemoryStoreProcessor: namespace обязателен")
        if key is None and key_property is None:
            raise ValueError("MemoryStoreProcessor: укажите key или key_property")
        super().__init__(name=name or f"memory_store:{namespace}")
        self.namespace = namespace
        self.key = key
        self.key_property = key_property
        self.value_property = value_property
        self.ttl_s = ttl_s

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope для ``ai.memory.write`` = после ``":"`` в namespace."""
        del exchange
        if ":" in self.namespace:
            return self.namespace.split(":", 1)[1]
        return self.namespace

    async def _run(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        del context
        backend = self._resolve_backend()
        if backend is None:
            _logger.debug("%s: MemoryProtocol backend недоступен — skip", self.name)
            return

        namespace = self._resolve_namespace(exchange)
        resolved_key = self._resolve_key(exchange)
        if not resolved_key:
            _logger.warning(
                "%s: key недоступен (key_property=%r) — skip",
                self.name,
                self.key_property,
            )
            return

        value = self._resolve_value(exchange)
        if value is None:
            _logger.debug(
                "%s: value=None (value_property=%r) — skip",
                self.name,
                self.value_property,
            )
            return

        try:
            await backend.store(namespace, resolved_key, value, ttl_s=self.ttl_s)
        except Exception as exc:
            _logger.warning("%s: store failed (%s) — drop", self.name, exc)

    def _resolve_namespace(self, exchange: Exchange[Any]) -> str:
        if "${tenant_id}" not in self.namespace:
            return self.namespace
        tenant = exchange.meta.tenant_id or "unknown"
        return self.namespace.replace("${tenant_id}", tenant)

    def _resolve_key(self, exchange: Exchange[Any]) -> str:
        if self.key_property is None:
            return self.key or ""

        parts = self.key_property.split(".")
        head = parts[0]
        if head == "meta":
            cursor: Any = exchange.meta
            for part in parts[1:]:
                cursor = getattr(cursor, part, None)
            return str(cursor) if cursor else ""

        if head == "body":
            cursor = exchange.in_message.body
            for part in parts[1:]:
                if cursor is None:
                    return ""
                cursor = (
                    cursor.get(part)
                    if isinstance(cursor, dict)
                    else getattr(cursor, part, None)
                )
            return str(cursor) if cursor else ""

        if head == "property":
            return str(exchange.get_property(parts[1])) if len(parts) > 1 else ""

        cursor = exchange.get_property(head)
        for part in parts[1:]:
            if cursor is None:
                return ""
            cursor = (
                cursor.get(part)
                if isinstance(cursor, dict)
                else getattr(cursor, part, None)
            )
        return str(cursor) if cursor else ""

    def _resolve_value(self, exchange: Exchange[Any]) -> Any:
        parts = self.value_property.split(".")
        head = parts[0]
        if head == "body":
            cursor: Any = exchange.in_message.body
            for part in parts[1:]:
                if cursor is None:
                    return None
                cursor = (
                    cursor.get(part)
                    if isinstance(cursor, dict)
                    else getattr(cursor, part, None)
                )
            return cursor

        cursor = exchange.get_property(head)
        for part in parts[1:]:
            if cursor is None:
                return None
            cursor = (
                cursor.get(part)
                if isinstance(cursor, dict)
                else getattr(cursor, part, None)
            )
        return cursor

    @staticmethod
    def _resolve_backend() -> Any | None:
        """Lazy-резолв :class:`MemoryProtocol`."""
        try:
            from src.backend.core.di.container import get_container

            container = get_container()
            if container is not None:
                return container.resolve_optional("memory_backend")
        except Exception as exc:
            _logger.debug("DI container resolve failed: %s", exc)
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"namespace": self.namespace}
        if self.key is not None:
            spec["key"] = self.key
        if self.key_property is not None:
            spec["key_property"] = self.key_property
        if self.value_property != "agent_result":
            spec["value_property"] = self.value_property
        if self.ttl_s is not None:
            spec["ttl_s"] = self.ttl_s
        return {"memory_store": spec}
