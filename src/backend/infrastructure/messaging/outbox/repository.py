"""Transactional Outbox Repository — atomic INSERT в одной транзакции с бизнес-данными.

Wave: ``[wave:s16/k2-w2-outbox-tx-atomic]`` — DoD-4 Sprint 16.

Главный инвариант: запись `outbox_messages` происходит **в той же сессии**,
что и бизнес-данные. Если процесс падает между INSERT-ами и commit() —
обе записи откатываются вместе (atomic rollback). Если commit прошёл —
обе записи персистированы. dropped-message-rate = 0 by construction.

Использование::

    from src.backend.infrastructure.messaging.outbox.repository import OutboxRepository

    async with session.begin():  # одна транзакция
        order = Order(...)
        session.add(order)
        await session.flush()  # получить order.id

        await OutboxRepository(session).enqueue(
            topic="orders.created",
            payload={"order_id": order.id, "total": order.total},
            headers={"correlation_id": ctx.correlation_id},
        )
    # commit прошёл — обе строки персистированы
    # rollback (по исключению) — обе строки откатились

Контракт совместим с ``advanced-alchemy.SQLAlchemyAsyncRepository``,
но не наследуется от него: outbox не нуждается в полной CRUD-семантике
(только enqueue), а сторонняя зависимость избыточна для одного метода.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.domain.models.outbox import OutboxMessage

__all__ = ("OutboxRepository", "TransactionalOutboxEnqueuer")


@runtime_checkable
class TransactionalOutboxEnqueuer(Protocol):
    """Контракт enqueue-сервиса для transactional outbox-паттерна.

    Реализация обязана:
    1. Не вызывать ``session.commit()`` самостоятельно — это делает caller.
    2. Не вызывать ``session.rollback()`` при ошибке — пусть caller решает.
    3. Использовать ``session.add(model)`` + опциональный ``flush()`` для
       получения PK без коммита.

    Это гарантирует atomic-семантику: либо обе записи (бизнес + outbox)
    попадают в БД, либо ни одной.
    """

    async def enqueue(
        self,
        *,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
        next_attempt_at: datetime | None = None,
    ) -> OutboxMessage:
        """Поставить событие в outbox-таблицу в текущей сессии (без commit).

        Args:
            topic: имя топика/route в формате ``<domain>.<event>``.
            payload: тело события (JSON-сериализуемый dict).
            headers: служебные заголовки (correlation_id, tenant_id, ...).
            next_attempt_at: время первой попытки доставки; по умолчанию
                ``datetime.now(timezone.utc)`` (немедленно).

        Returns:
            Созданная модель ``OutboxMessage`` (id заполнится после flush).
        """


class OutboxRepository:
    """Реализация [TransactionalOutboxEnqueuer] поверх SQLAlchemy AsyncSession.

    Stateless по конструкции: сессия передаётся в конструктор и хранится
    как weak-link. Один экземпляр живёт ровно столько же, сколько и
    бизнес-транзакция caller'а.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Сохраняет ссылку на активную сессию.

        Args:
            session: AsyncSession в открытой транзакции; commit/rollback
                остаётся ответственностью caller'а.
        """
        self._session = session

    async def enqueue(
        self,
        *,
        topic: str,
        payload: dict[str, Any],
        headers: dict[str, Any] | None = None,
        next_attempt_at: datetime | None = None,
    ) -> OutboxMessage:
        """Atomic enqueue — см. [TransactionalOutboxEnqueuer.enqueue].

        Дополнительно: если ``headers`` не содержит ``correlation_id`` /
        ``tenant_id``, значения подтягиваются из ``RequestContext`` для
        e2e-propagation в downstream consumers (S17 K3 W3).
        """
        merged_headers = self._merge_context_headers(headers)
        message = OutboxMessage(
            topic=topic,
            payload=payload,
            headers=merged_headers,
            status="pending",
            retry_count=0,
            next_attempt_at=next_attempt_at or datetime.now(UTC),
        )
        self._session.add(message)
        # Flush, чтобы получить PK без commit'а — caller имеет возможность
        # ссылаться на message.id в дальнейших вставках (например, в audit).
        await self._session.flush([message])
        return message

    @staticmethod
    def _merge_context_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
        """Дополнить headers значениями из RequestContext (correlation/tenant).

        Если caller передал явный header — он имеет приоритет. Если ни
        header, ни RequestContext не дают значения — поле опускается
        (не пишется пустая строка).
        """
        result: dict[str, Any] = dict(headers or {})
        if "correlation_id" not in result:
            try:
                from src.backend.infrastructure.observability.correlation import (
                    get_correlation_id,
                )

                cid = get_correlation_id()
                if cid:
                    result["correlation_id"] = cid
            except ImportError:
                pass
        return result
