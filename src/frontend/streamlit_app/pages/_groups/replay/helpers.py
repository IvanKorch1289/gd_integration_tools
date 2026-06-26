"""DLQ replay helpers — extracted from pages/54_Replay_DLQ.py (S173).

Содержит: _get_outbox(), _run_async(), _ensure_demo_data() — инфраструктура
для UI рендеринга DLQ replay.
"""

from __future__ import annotations

import asyncio
from typing import Any

import streamlit as st

from src.backend.core.messaging import FakeOutbox, OutboxBackend, OutboxEvent


@st.cache_resource
def get_outbox() -> OutboxBackend:
    """Кэшированная in-memory Fake-инстанция Outbox.

    В production-сборке здесь будет резолв через DI-контейнер
    (после готовности S5 К2 ``OutboxDispatcher``).

    Returns:
        Инстанция OutboxBackend (Fake/Real в зависимости от среды).
    """
    return FakeOutbox()


def run_async(coro: Any) -> Any:
    """Выполняет async-coroutine в текущем потоке Streamlit.

    Streamlit-runner — синхронный, поэтому каждый вызов оборачивается
    в собственный event loop. ``asyncio.run`` корректен в контексте
    Streamlit-страницы (нет вложенных loops).

    Args:
        coro: coroutine-объект.

    Returns:
        Результат выполнения coroutine.
    """
    return asyncio.run(coro)


def ensure_demo_data(outbox: OutboxBackend) -> None:
    """Однократная инициализация demo-событий для Fake-backend.

    Production-backend (S5 К2) сам наполняется через ``enqueue`` из
    failed-dispatch путей; здесь — только seed для UX-демонстрации.

    Args:
        outbox: backend-инстанция.
    """
    if not isinstance(outbox, FakeOutbox):
        return
    if outbox._events:  # noqa: SLF001 — Fake-only debug-доступ к локальному store
        return

    samples = [
        OutboxEvent(
            transport="http",
            action="credit.score.calculate",
            payload={"order_id": 101, "amount": 50000},
            tenant_id="bank-main",
            correlation_id="corr-001",
        ),
        OutboxEvent(
            transport="kafka",
            action="audit.event.publish",
            payload={"event": "user_login", "user_id": 42},
            tenant_id="bank-main",
            correlation_id="corr-002",
        ),
        OutboxEvent(
            transport="webhook",
            action="notify.partner",
            payload={"partner": "skb", "message": "ack"},
            tenant_id="bank-corp",
            correlation_id="corr-003",
        ),
    ]

    async def _seed() -> None:
        for ev in samples:
            await outbox.enqueue(ev)
            await outbox._force_to_dlq(ev.event_id, RuntimeError("demo failure"))  # noqa: SLF001

    run_async(_seed())
