"""Unit-тесты для [OutboxDispatcher] (S8A K2 W2, L-scope).

Покрытые сценарии:

* ``test_disabled_start_is_noop`` — feature-flag ``enabled=False``.
* ``test_poll_empty_no_delivery`` — пустой источник, deliverer не звался.
* ``test_poll_some_delivered_and_acked`` — счастливый путь.
* ``test_delivery_fail_transient_then_acked`` — retry-loop восстанавливается.
* ``test_delivery_fail_permanent_handoff_to_dlq`` — исчерпание retry → DLQ.
* ``test_shutdown_during_batch_graceful`` — graceful дренаж при stop.

Все тесты не зависят от реальной БД и реальных брокеров; используют
[FakeOutbox] + асинхронные list/deque pending-источники + мок deliverer'а.
"""


from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence

import pytest

from src.backend.core.messaging.outbox import FakeOutbox, OutboxEvent, OutboxEventStatus
from src.backend.core.utils.task_registry import reset_task_registry
from src.backend.infrastructure.messaging.outbox.dispatcher import (
    DLQHandler,
    OutboxDispatcher,
)


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    """Сбрасываем singleton TaskRegistry между тестами для изоляции."""
    reset_task_registry()
    yield
    reset_task_registry()


@pytest.fixture
def outbox() -> FakeOutbox:
    """Чистый FakeOutbox — используется как DLQ-store."""
    return FakeOutbox()


def _make_event(action: str = "api.send") -> OutboxEvent:
    """Хелпер: создать pending-событие по умолчанию."""
    return OutboxEvent(transport="http", action=action, payload={"k": "v"})


class _ListPendingSource:
    """Pending-источник: одноразовая выдача предзаписанной пачки.

    После выдачи возвращает пустой список (имитирует «таблица очищена»).
    """

    def __init__(self, events: list[OutboxEvent]) -> None:
        self._events = list(events)
        self.calls = 0

    async def __call__(self, batch_size: int) -> Sequence[OutboxEvent]:
        self.calls += 1
        batch = self._events[:batch_size]
        self._events = self._events[batch_size:]
        return batch


class _AckRecorder:
    """Хелпер: записывает event_id-ы успешно подтверждённых событий."""

    def __init__(self) -> None:
        self.acked: list[str] = []

    async def __call__(self, event: OutboxEvent) -> None:
        self.acked.append(event.event_id)


class _DLQRecorder:
    """Хелпер: реализация [DLQHandler], собирает handoff-вызовы."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []  # (event_id, reason_class)

    async def send(self, event: OutboxEvent, reason: BaseException) -> None:
        self.calls.append((event.event_id, type(reason).__name__))


async def test_disabled_start_is_noop(outbox: FakeOutbox) -> None:
    """При ``enabled=False`` start не создаёт задачу, is_running=False."""
    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=_ListPendingSource([]),
        ack=_AckRecorder(),
        deliverer=_noop_deliverer,
        enabled=False,
    )
    await dispatcher.start()

    assert dispatcher.is_running is False

    # Повторный stop тоже идемпотентен.
    await dispatcher.stop()


async def test_poll_empty_no_delivery(outbox: FakeOutbox) -> None:
    """Пустой pending → deliverer не звался, ack не звался."""
    source = _ListPendingSource([])
    ack = _AckRecorder()
    deliverer = _CountingDeliverer()

    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=source,
        ack=ack,
        deliverer=deliverer,
        poll_interval=0.01,
    )
    await dispatcher.start()
    # Дать петле прокрутить минимум 2 итерации.
    await asyncio.sleep(0.05)
    await dispatcher.stop(timeout=1.0)

    assert deliverer.calls == 0
    assert ack.acked == []
    assert source.calls >= 1


async def test_poll_some_delivered_and_acked(outbox: FakeOutbox) -> None:
    """Pending события доставляются и подтверждаются ack."""
    events = [_make_event("a.1"), _make_event("a.2")]
    source = _ListPendingSource(events)
    ack = _AckRecorder()
    deliverer = _CountingDeliverer()

    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=source,
        ack=ack,
        deliverer=deliverer,
        poll_interval=0.01,
        max_retries=1,
    )
    await dispatcher.start()
    # Ждём, пока оба события не будут acked (с safety-таймаутом).
    for _ in range(50):
        if len(ack.acked) >= 2:
            break
        await asyncio.sleep(0.01)
    await dispatcher.stop(timeout=1.0)

    assert set(ack.acked) == {e.event_id for e in events}
    assert deliverer.calls == 2
    # Статус событий обновлён в DELIVERED.
    assert all(e.status is OutboxEventStatus.DELIVERED for e in events)


async def test_delivery_fail_transient_then_acked(outbox: FakeOutbox) -> None:
    """Transient ошибка → retry; в итоге успех + ack."""
    event = _make_event("retry.case")
    source = _ListPendingSource([event])
    ack = _AckRecorder()
    deliverer = _FlakyDeliverer(fail_times=2)

    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=source,
        ack=ack,
        deliverer=deliverer,
        poll_interval=0.01,
        max_retries=5,
        retry_backoff_seconds=0.001,
    )
    await dispatcher.start()
    for _ in range(100):
        if ack.acked:
            break
        await asyncio.sleep(0.01)
    await dispatcher.stop(timeout=1.0)

    assert ack.acked == [event.event_id]
    # Был ровно один ack, но deliverer звался fail_times+1 раз.
    assert deliverer.calls == 3
    assert event.status is OutboxEventStatus.DELIVERED


async def test_delivery_fail_permanent_handoff_to_dlq(outbox: FakeOutbox) -> None:
    """Исчерпание retry → событие уходит в DLQ через [DLQHandler]."""
    event = _make_event("dlq.case")
    source = _ListPendingSource([event])
    ack = _AckRecorder()
    deliverer = _AlwaysFailDeliverer()
    dlq = _DLQRecorder()

    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=source,
        ack=ack,
        deliverer=deliverer,
        dlq=dlq,
        poll_interval=0.01,
        max_retries=3,
        retry_backoff_seconds=0.001,
    )
    await dispatcher.start()
    for _ in range(100):
        if dlq.calls:
            break
        await asyncio.sleep(0.01)
    await dispatcher.stop(timeout=1.0)

    assert ack.acked == []
    assert dlq.calls == [(event.event_id, "RuntimeError")]
    # Делитель звался ровно ``max_retries`` раз.
    assert deliverer.calls == 3
    # Проверяем, что объект DLQHandler соответствует Protocol.
    assert isinstance(dlq, DLQHandler)


async def test_shutdown_during_batch_graceful(outbox: FakeOutbox) -> None:
    """При stop во время батча — недоставленные не ack'аются.

    Сценарий: медленный deliverer задерживает обработку первого события;
    мы стопим диспетчер пока он спит в backoff между retry — оставшиеся
    в батче события не должны быть подтверждены.
    """
    events = [_make_event("g.1"), _make_event("g.2"), _make_event("g.3")]
    source = _ListPendingSource(events)
    ack = _AckRecorder()
    started = asyncio.Event()
    blocker = asyncio.Event()

    async def slow_failing_deliverer(_event: OutboxEvent) -> None:
        started.set()
        # Заморозим первое событие в первой попытке — потом stop отменит.
        await blocker.wait()
        raise RuntimeError("never-recovers")

    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=source,
        ack=ack,
        deliverer=slow_failing_deliverer,
        poll_interval=0.01,
        max_retries=5,
        retry_backoff_seconds=10.0,  # большой backoff — гарантирует sleep
    )
    await dispatcher.start()
    # Ждём первого вызова deliverer'а (диспетчер «застрял»).
    await asyncio.wait_for(started.wait(), timeout=2.0)
    # Снимаем блокировку: deliverer кидает исключение, dispatcher уходит
    # в долгий backoff sleep — оттуда stop его и разбудит.
    blocker.set()
    await dispatcher.stop(timeout=1.0)

    # Не было ни одного успешного ack — backend кинул, и stop прервал retry.
    assert ack.acked == []
    # is_running вернулось в False.
    assert dispatcher.is_running is False


# ---------------------------------------------------------------------------
# Хелперы-фейки. Объявлены модулем-уровневыми, чтобы быть picklable, хотя
# здесь pickle и не нужен — просто чище.
# ---------------------------------------------------------------------------


class _CountingDeliverer:
    """Deliverer, который успешно «отправляет» и считает вызовы."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _event: OutboxEvent) -> None:
        self.calls += 1


class _FlakyDeliverer:
    """Deliverer: первые ``fail_times`` вызовов кидают, далее успех."""

    def __init__(self, *, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0

    async def __call__(self, _event: OutboxEvent) -> None:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"transient failure #{self.calls}")


class _AlwaysFailDeliverer:
    """Deliverer, который всегда падает (permanent failure)."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _event: OutboxEvent) -> None:
        self.calls += 1
        raise RuntimeError(f"permanent failure #{self.calls}")


async def _noop_deliverer(_event: OutboxEvent) -> None:
    """No-op deliverer для пустых сценариев."""
    return


# ---------------------------------------------------------------------------
# Доп-тесты для default _BackendDLQHandler — проверяем, что без явного dlq
# событие всё равно попадает в FakeOutbox.list_dlq().
# ---------------------------------------------------------------------------


async def test_default_dlq_handler_uses_backend_enqueue(outbox: FakeOutbox) -> None:
    """Без явного ``dlq`` — handoff идёт через ``backend.enqueue`` с DLQ."""
    event = _make_event("default.dlq")
    source = _ListPendingSource([event])
    ack = _AckRecorder()
    deliverer = _AlwaysFailDeliverer()

    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=source,
        ack=ack,
        deliverer=deliverer,
        poll_interval=0.01,
        max_retries=2,
        retry_backoff_seconds=0.001,
    )
    await dispatcher.start()
    for _ in range(100):
        dlq_items = await outbox.list_dlq()
        if dlq_items:
            break
        await asyncio.sleep(0.01)
    await dispatcher.stop(timeout=1.0)

    dlq_items = await outbox.list_dlq()
    assert len(dlq_items) == 1
    assert dlq_items[0].event_id == event.event_id
    assert dlq_items[0].status is OutboxEventStatus.DLQ
    assert dlq_items[0].error_class == "RuntimeError"


# ---------------------------------------------------------------------------
# Доп-тест: deque-pending-source, имитирует «инкрементальную» очередь —
# гарантирует, что dispatcher не падает на меняющемся снапшоте.
# ---------------------------------------------------------------------------


async def test_dispatcher_handles_incremental_pending(outbox: FakeOutbox) -> None:
    """Очередь пополняется во время работы; dispatcher продолжает."""

    backlog: deque[OutboxEvent] = deque()

    async def source(batch_size: int) -> Sequence[OutboxEvent]:
        batch: list[OutboxEvent] = []
        for _ in range(min(batch_size, len(backlog))):
            batch.append(backlog.popleft())
        return batch

    ack = _AckRecorder()
    deliverer = _CountingDeliverer()
    dispatcher = OutboxDispatcher(
        backend=outbox,
        pending_source=source,
        ack=ack,
        deliverer=deliverer,
        poll_interval=0.01,
        max_retries=1,
    )
    await dispatcher.start()
    backlog.append(_make_event("inc.1"))
    await asyncio.sleep(0.05)
    backlog.append(_make_event("inc.2"))
    for _ in range(100):
        if len(ack.acked) >= 2:
            break
        await asyncio.sleep(0.01)
    await dispatcher.stop(timeout=1.0)

    assert len(ack.acked) == 2
    assert deliverer.calls == 2


# ---------------------------------------------------------------------------
# Sprint 4.2 (L10 Observability): jitter в _compute_sleep_for.
# Mirror pattern из infrastructure/workflow/runner.py:_compute_backoff.
# ---------------------------------------------------------------------------


def _make_dispatcher_for_sleep_test(
    outbox: FakeOutbox,
    *,
    retry_backoff_seconds: float,
    retry_jitter: float | None = None,
    max_retries: int = 5,
) -> OutboxDispatcher:
    """Хелпер: bare-bones диспетчер для unit-тестов _compute_sleep_for."""
    kwargs: dict[str, object] = dict(
        backend=outbox,
        pending_source=_ListPendingSource([]),
        ack=_AckRecorder(),
        deliverer=_noop_deliverer,
        retry_backoff_seconds=retry_backoff_seconds,
        max_retries=max_retries,
        enabled=False,  # не запускаем background-task в unit-тестах
    )
    if retry_jitter is not None:
        kwargs["retry_jitter"] = retry_jitter
    return OutboxDispatcher(**kwargs)  # type: ignore[arg-type]


def test_compute_sleep_for_zero_jitter_is_deterministic(outbox: FakeOutbox) -> None:
    """retry_jitter=0 → sleep_for == base * 2 ** (attempt-1), без randomness.

    Сохраняем backward-compat со старой реализацией без jitter.
    """
    dispatcher = _make_dispatcher_for_sleep_test(
        outbox, retry_backoff_seconds=0.5, retry_jitter=0.0
    )
    for attempt in range(1, 8):
        expected = 0.5 * (2 ** (attempt - 1))
        assert dispatcher._compute_sleep_for(attempt) == expected


def test_compute_sleep_for_default_jitter_within_bounds(outbox: FakeOutbox) -> None:
    """retry_jitter=0.2 → sleep_for ∈ [raw*0.8, raw*1.2] для любого attempt.

    Покрывает consistent-pattern с DurableWorkflowRunner._compute_backoff.
    """
    base = 0.1
    dispatcher = _make_dispatcher_for_sleep_test(
        outbox, retry_backoff_seconds=base, retry_jitter=0.2
    )
    raw_for = lambda attempt: base * (2 ** (attempt - 1))  # noqa: E731
    for attempt in range(1, 6):
        raw = raw_for(attempt)
        for _ in range(50):  # многократные samples для robustness
            sleep_for = dispatcher._compute_sleep_for(attempt)
            assert raw * 0.8 <= sleep_for <= raw * 1.2, (
                f"attempt={attempt} raw={raw} sleep_for={sleep_for}"
            )


def test_compute_sleep_for_default_jitter_is_randomized(outbox: FakeOutbox) -> None:
    """retry_jitter=0.2 → последовательные вызовы дают разные sleep_for.

    Защита от регрессии «забыл применить uniform».
    """
    dispatcher = _make_dispatcher_for_sleep_test(
        outbox, retry_backoff_seconds=1.0, retry_jitter=0.2
    )
    samples = {dispatcher._compute_sleep_for(2) for _ in range(30)}
    # 30 samples с ±20% jitter — крайне маловероятно все совпадут.
    assert len(samples) > 5


def test_compute_sleep_for_never_negative(outbox: FakeOutbox) -> None:
    """Даже при экстремальном jitter=0.999 sleep_for остаётся ≥ 0."""
    dispatcher = _make_dispatcher_for_sleep_test(
        outbox, retry_backoff_seconds=0.01, retry_jitter=0.999
    )
    for attempt in range(1, 6):
        sleep_for = dispatcher._compute_sleep_for(attempt)
        assert sleep_for >= 0.0
        # Конечное значение, не NaN/inf.
        assert sleep_for == sleep_for
        assert abs(sleep_for) != float("inf")


def test_outbox_dispatcher_default_retry_jitter_is_zero_point_two(
    outbox: FakeOutbox,
) -> None:
    """Default retry_jitter=0.2 (±20%) — consistent с workflow runner."""
    dispatcher = _make_dispatcher_for_sleep_test(outbox, retry_backoff_seconds=1.0)
    assert dispatcher._retry_jitter == 0.2  # noqa: S101  # default check


async def test_dispatch_one_applies_jitter_via_wait_for_timeout(
    outbox: FakeOutbox,
) -> None:
    """Integration: retry-loop передаёт jittered sleep_for в asyncio.wait_for.

    Перехватываем asyncio.wait_for в модуле dispatcher'а — фиксируем
    ``timeout``-аргумент для каждого retry-вызова и проверяем, что он
    лежит в jittered-диапазоне, а не равен детерминированному base*2^(n-1).
    """
    captured: list[float] = []

    real_wait_for = asyncio.wait_for

    async def capturing_wait_for(awaitable, *, timeout=None, **kwargs):  # type: ignore[no-untyped-def]
        # Ловим только retry-вызовы (timeout есть + позиционный аргумент —
        # ``_stopping.wait()``). Фильтруем ``_poll_and_dispatch`` pause-вызов
        # по типу awaitable (Event.wait() vs Event.wait()).
        if timeout is not None:
            captured.append(float(timeout))
        return await real_wait_for(awaitable, timeout=timeout, **kwargs)

    # Monkeypatch на уровне модуля dispatcher'а — внутри retry-loop'а
    # ``asyncio.wait_for`` смотрит на этот binding.
    import src.backend.infrastructure.messaging.outbox.dispatcher as _dsp

    original_wait_for = _dsp.asyncio.wait_for
    _dsp.asyncio.wait_for = capturing_wait_for
    try:
        base = 0.05
        event = _make_event("jitter.integration")
        dispatcher = OutboxDispatcher(
            backend=outbox,
            pending_source=_ListPendingSource([event]),
            ack=_AckRecorder(),
            deliverer=_AlwaysFailDeliverer(),
            poll_interval=0.01,
            max_retries=3,
            retry_backoff_seconds=base,
            retry_jitter=0.2,
        )
        await dispatcher.start()
        for _ in range(100):
            dlq_calls = await outbox.list_dlq()
            if dlq_calls:
                break
            await asyncio.sleep(0.01)
        await dispatcher.stop(timeout=1.0)
    finally:
        _dsp.asyncio.wait_for = original_wait_for

    # Было ровно max_retries-1 backoff-вызовов (после последней попытки
    # sleep не нужен — сразу DLQ). Отфильтровываем poll_interval (< base/2)
    # и stop timeout (> 2 * base * (1 + jitter)) — оставляем только retry-паузы.
    upper = 2 * base * 1.5
    retry_timeouts = [t for t in captured if base * 0.5 <= t <= upper]
    assert len(retry_timeouts) == 2, f"expected 2 retry timeouts, got {captured}"
    # attempt=1 → raw=base, attempt=2 → raw=2*base
    raw_seq = [base * (2 ** (i - 1)) for i in (1, 2)]
    for raw, t in zip(raw_seq, retry_timeouts, strict=True):
        assert raw * 0.8 <= t <= raw * 1.2, (
            f"raw={raw} captured={t} outside ±20% jitter window"
        )
    # И хотя бы один sleep отличается от детерминированного raw → jitter применён.
    assert any(
        abs(t - raw) > 1e-9 for raw, t in zip(raw_seq, retry_timeouts, strict=True)
    ), f"all timeouts match deterministic raw — jitter not applied: {retry_timeouts}"
