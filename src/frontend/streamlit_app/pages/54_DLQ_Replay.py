"""Streamlit-страница DLQ Replay UI (S7 K5).

Назначение
----------
Универсальный оператор-инструмент для управления Dead-Letter Queue
(Outbox-pattern) поверх контракта ``src.backend.core.messaging.OutboxBackend``.

В качестве backend по умолчанию используется ``FakeOutbox`` (in-memory)
до момента, когда S5 К2 завершит коммит реального ``OutboxDispatcher``.
Переключение управляется feature_flag ``dlq_unified_enabled``.

Возможности
-----------
* фильтрация событий DLQ через sidebar (transport / action / timestamp range /
  error_class / tenant_id);
* пагинированная таблица событий через ``st.dataframe``;
* bulk replay (multiselect + button → ``outbox.replay(event_ids)``);
* manual edit-and-replay (``st.text_area`` для payload + override_payload).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any

# Поднимаем корень проекта в sys.path для корректного импорта в Streamlit-режиме.
import streamlit as st  # noqa: E402

st.set_page_config(
    page_title="DLQ Replay", page_icon=":envelope_with_arrow:", layout="wide"
)
st.header("DLQ Replay")

# ---------------------------------------------------------------------------
# Feature-flag guard
# ---------------------------------------------------------------------------
try:
    from src.backend.core.config.features import feature_flags as _ff  # noqa: PLC0415

    _flag_enabled: bool = bool(getattr(_ff, "dlq_unified_enabled", False))
except Exception:  # noqa: BLE001
    _flag_enabled = False

with st.sidebar:
    st.subheader("Настройки")
    st.toggle(
        "DLQ Replay UI",
        value=_flag_enabled,
        help="feature_flags.dlq_unified_enabled (FEATURE_DLQ_UNIFIED_ENABLED)",
        disabled=True,
    )
    st.caption(
        "Для включения установите `FEATURE_DLQ_UNIFIED_ENABLED=true` "
        "или обновите `features.yaml`."
    )

if not _flag_enabled:
    st.warning(
        "DLQ Replay UI отключён (feature_flag: `dlq_unified_enabled = false`). "
        "Установите `FEATURE_DLQ_UNIFIED_ENABLED=true` для активации."
    )
    st.stop()

# ---------------------------------------------------------------------------
# Outbox backend (Fake до момента готовности S5 К2 production-backend)
# ---------------------------------------------------------------------------
from src.backend.core.messaging import (  # noqa: PLC0415, E402
    FakeOutbox,
    OutboxBackend,
    OutboxEvent,
    OutboxEventStatus,
)


@st.cache_resource
def _get_outbox() -> OutboxBackend:
    """Кэшированная in-memory Fake-инстанция Outbox.

    В production-сборке здесь будет резолв через DI-контейнер
    (после готовности S5 К2 ``OutboxDispatcher``).

    Returns:
        Инстанция [OutboxBackend] (Fake/Real в зависимости от среды).
    """
    return FakeOutbox()


def _run_async(coro: Any) -> Any:
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


def _ensure_demo_data(outbox: OutboxBackend) -> None:
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

    _samples = [
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
        for ev in _samples:
            await outbox.enqueue(ev)
            await outbox._force_to_dlq(ev.event_id, RuntimeError("demo failure"))  # noqa: SLF001

    _run_async(_seed())


_outbox: OutboxBackend = _get_outbox()
_ensure_demo_data(_outbox)

# ---------------------------------------------------------------------------
# Sidebar — filters
# ---------------------------------------------------------------------------
with st.sidebar:
    st.subheader("Фильтры DLQ")
    _transport_filter: str = st.text_input(
        "Transport", value="", help="http / kafka / grpc / webhook / soap / mqtt / ..."
    )
    _action_filter: str = st.text_input("Action", value="", help="Имя action или route")
    _error_class_filter: str = st.text_input(
        "Error class",
        value="",
        help="Имя класса исключения (RuntimeError, TimeoutError, ...)",
    )
    _tenant_filter: str = st.text_input("Tenant ID", value="", help="Tenant-контекст")
    _hours_back: int = st.number_input(
        "За последние N часов", min_value=1, max_value=24 * 7, value=24, step=1
    )
    _limit: int = st.number_input(
        "Limit", min_value=10, max_value=1000, value=100, step=10
    )

# ---------------------------------------------------------------------------
# Загрузка DLQ
# ---------------------------------------------------------------------------
_since = datetime.now(timezone.utc) - timedelta(hours=int(_hours_back))

_events: list[OutboxEvent] = list(
    _run_async(
        _outbox.list_dlq(
            transport=_transport_filter or None,
            action=_action_filter or None,
            error_class=_error_class_filter or None,
            tenant_id=_tenant_filter or None,
            since=_since,
            limit=int(_limit),
        )
    )
)

# ---------------------------------------------------------------------------
# Сводка
# ---------------------------------------------------------------------------
_col_stats_1, _col_stats_2, _col_stats_3 = st.columns(3)
_col_stats_1.metric("Событий найдено", len(_events))
_col_stats_2.metric("С payload", sum(1 for e in _events if e.payload))
_col_stats_3.metric("Уникальных transports", len({e.transport for e in _events}))

# ---------------------------------------------------------------------------
# Таблица событий
# ---------------------------------------------------------------------------
st.subheader("События в DLQ")

if not _events:
    st.info("В DLQ нет событий по текущим фильтрам.")
    st.stop()

_rows: list[dict[str, Any]] = [
    {
        "event_id": e.event_id,
        "transport": e.transport,
        "action": e.action,
        "tenant_id": e.tenant_id or "",
        "error_class": e.error_class or "",
        "error_message": (e.error_message or "")[:80],
        "retry_count": e.retry_count,
        "created_at": e.created_at.isoformat(timespec="seconds"),
    }
    for e in _events
]

st.dataframe(_rows, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Bulk replay
# ---------------------------------------------------------------------------
st.subheader("Bulk replay")

_event_id_options: list[str] = [e.event_id for e in _events]
_event_label_by_id: dict[str, str] = {
    e.event_id: f"{e.transport}:{e.action} [{e.event_id[:8]}]" for e in _events
}

_selected_ids: list[str] = st.multiselect(
    "Выберите события для replay",
    options=_event_id_options,
    format_func=lambda eid: _event_label_by_id.get(eid, eid),
    help="События будут переведены из DLQ обратно в PENDING.",
)

_col_bulk_1, _col_bulk_2 = st.columns([1, 1])
with _col_bulk_1:
    _dry_run_bulk: bool = st.checkbox("Dry-run", value=False, key="bulk_dry_run")
with _col_bulk_2:
    _bulk_clicked = st.button(
        "Replay selected",
        type="primary",
        disabled=not _selected_ids,
        use_container_width=True,
    )

if _bulk_clicked and _selected_ids:
    _affected = _run_async(_outbox.replay(_selected_ids, dry_run=_dry_run_bulk))
    if _dry_run_bulk:
        st.info(f"Dry-run: {_affected} событий пройдёт replay.")
    else:
        st.success(f"Replay выполнен для {_affected} событий.")
    st.rerun()

# ---------------------------------------------------------------------------
# Manual edit-and-replay
# ---------------------------------------------------------------------------
st.subheader("Manual edit-and-replay")

_manual_event_id: str = st.selectbox(
    "Событие",
    options=_event_id_options,
    format_func=lambda eid: _event_label_by_id.get(eid, eid),
    key="manual_event_id",
)

_target_event: OutboxEvent | None = next(
    (e for e in _events if e.event_id == _manual_event_id), None
)

if _target_event is not None:
    _initial_payload = json.dumps(_target_event.payload, ensure_ascii=False, indent=2)
    _override_raw: str = st.text_area(
        "Override payload (JSON)",
        value=_initial_payload,
        height=200,
        help="Отредактируйте payload — он будет использован при replay.",
    )

    _col_manual_1, _col_manual_2 = st.columns([1, 1])
    with _col_manual_1:
        _dry_run_manual: bool = st.checkbox(
            "Dry-run", value=False, key="manual_dry_run"
        )
    with _col_manual_2:
        _manual_clicked = st.button(
            "Replay with override", type="primary", use_container_width=True
        )

    if _manual_clicked:
        try:
            _override_payload: dict[str, Any] = json.loads(_override_raw)
        except json.JSONDecodeError as _json_err:
            st.error(f"Невалидный JSON в override: {_json_err}")
        else:
            _affected = _run_async(
                _outbox.replay(
                    [_manual_event_id],
                    dry_run=_dry_run_manual,
                    override_payload=_override_payload,
                )
            )
            if _affected:
                msg = (
                    "Dry-run: payload override применился бы"
                    if _dry_run_manual
                    else "Replay с override выполнен"
                )
                st.success(msg)
                if not _dry_run_manual:
                    st.rerun()
            else:
                st.warning(
                    "Событие не в DLQ или уже было перенесено — replay не выполнен."
                )

# ---------------------------------------------------------------------------
# Подвал — текущий статус backend
# ---------------------------------------------------------------------------
with st.expander("Backend info", expanded=False):
    st.write(f"Тип backend: `{type(_outbox).__name__}`")
    if isinstance(_outbox, FakeOutbox):
        _stats = _run_async(_outbox.stats())
        st.write("Распределение по статусам:")
        st.json(
            {
                OutboxEventStatus(k).value
                if k in {s.value for s in OutboxEventStatus}
                else k: v
                for k, v in _stats.items()
            }
        )
    st.caption(
        "Когда S5 К2 закоммитит OutboxDispatcher, DI-контейнер автоматически "
        "заменит Fake на production-backend (Postgres-table dlq_events)."
    )
