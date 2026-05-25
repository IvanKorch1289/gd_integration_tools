"""MemoryRecallProcessor — DSL-обёртка :meth:`MemoryProtocol.recall` (S27 W3).

Получает релевантные записи из :class:`MemoryProtocol`-backend'а
(LangGraph Checkpointer / Mem0 / AgentMemory). См. ADR-NEW-18.

YAML контракт::

    steps:
      - memory_recall:
          namespace: "acme:credit_chat"
          query_property: body.user_input
          k: 5
          result_property: memory_context

Python контракт::

    builder.ai_memory_recall(namespace="acme:credit_chat",
                              query_property="body.user_input")

Capability ``ai.memory.read.<scope>`` обязательна; ``scope`` = подстрока
namespace после ``":"`` или ``"*"``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.agent_dsl._base import BaseAIProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("MemoryRecallProcessor",)

_logger = logging.getLogger(__name__)


class MemoryRecallProcessor(BaseAIProcessor):
    """Поиск релевантных записей памяти (RAG-style retrieval).

    Args:
        namespace: ``"<tenant_id>:<scope>"`` — изоляция по tenant.
            Можно использовать static значение или включать
            ``${tenant_id}`` — будет подставлен из ``exchange.meta.tenant_id``.
        query: Опц. статичный текст запроса.
        query_property: Опц. dot-path к динамическому запросу
            (``"body.user_input"``). Если указан вместе с ``query`` —
            приоритет у property.
        k: Максимум возвращаемых записей. Default ``5``.
        result_property: Свойство exchange для результата. Default
            ``"memory_recall"``.
        name: Имя процессора.
    """

    required_capability: ClassVar[str | None] = "ai.memory.read"
    audit_event: ClassVar[str | None] = "ai.memory.recall"
    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(
        self,
        *,
        namespace: str,
        query: str | None = None,
        query_property: str | None = None,
        k: int = 5,
        result_property: str = "memory_recall",
        name: str | None = None,
    ) -> None:
        if not namespace:
            raise ValueError("MemoryRecallProcessor: namespace обязателен")
        if query is None and query_property is None:
            raise ValueError(
                "MemoryRecallProcessor: укажите query или query_property"
            )
        if k < 1:
            raise ValueError(
                f"MemoryRecallProcessor: k должен быть >=1, получено {k}"
            )
        super().__init__(name=name or f"memory_recall:{namespace}")
        self.namespace = namespace
        self.query = query
        self.query_property = query_property
        self.k = k
        self.result_property = result_property

    def _capability_scope(self, exchange: "Exchange[Any]") -> str | None:
        """Scope для ``ai.memory.read`` = после ``":"`` в namespace."""
        del exchange
        if ":" in self.namespace:
            return self.namespace.split(":", 1)[1]
        return self.namespace

    async def _run(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        del context
        backend = self._resolve_backend()
        if backend is None:
            _logger.debug("%s: MemoryProtocol backend недоступен — skip", self.name)
            exchange.set_property(self.result_property, [])
            return

        namespace = self._resolve_namespace(exchange)
        query = self._resolve_query(exchange)
        if not query:
            exchange.set_property(self.result_property, [])
            return

        try:
            records = await backend.recall(namespace, query, k=self.k)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("%s: recall failed (%s) — empty result", self.name, exc)
            records = []

        exchange.set_property(self.result_property, list(records))

    def _resolve_namespace(self, exchange: "Exchange[Any]") -> str:
        """Подставить ``${tenant_id}`` placeholder."""
        if "${tenant_id}" not in self.namespace:
            return self.namespace
        tenant = exchange.meta.tenant_id or "unknown"
        return self.namespace.replace("${tenant_id}", tenant)

    def _resolve_query(self, exchange: "Exchange[Any]") -> str:
        """Достать query из property или вернуть статичный."""
        if self.query_property is not None:
            parts = self.query_property.split(".")
            head = parts[0]
            if head == "body":
                cursor: Any = exchange.in_message.body
                for part in parts[1:]:
                    if cursor is None:
                        return ""
                    cursor = (
                        cursor.get(part)
                        if isinstance(cursor, dict)
                        else getattr(cursor, part, None)
                    )
                return str(cursor) if cursor else ""

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

        return self.query or ""

    @staticmethod
    def _resolve_backend() -> Any | None:
        """Lazy-резолв :class:`MemoryProtocol` backend через DI."""
        try:
            from src.backend.core.di.container import get_container

            container = get_container()
            if container is not None:
                return container.resolve_optional("memory_backend")
        except Exception as exc:  # noqa: BLE001
            _logger.debug("DI container resolve failed: %s", exc)
        return None

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {"namespace": self.namespace, "k": self.k}
        if self.query is not None:
            spec["query"] = self.query
        if self.query_property is not None:
            spec["query_property"] = self.query_property
        if self.result_property != "memory_recall":
            spec["result_property"] = self.result_property
        return {"memory_recall": spec}
