"""DLQ Replay render — extracted from pages/54_Replay_DLQ.py (S173).

Полный UI: filters sidebar → events table → bulk replay → manual edit-replay.
Использует helpers из ``_groups.replay.helpers``.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

from src.backend.core.messaging import (
    FakeOutbox,
    OutboxBackend,
    OutboxEvent,
    OutboxEventStatus,
)
from src.frontend.streamlit_app.pages._groups.replay.helpers import (
    ensure_demo_data,
    get_outbox,
    run_async,
)


def render_dlq_replay() -> None:
    """Render full DLQ Replay UI (filters + table + bulk + manual)."""
    outbox: OutboxBackend = get_outbox()
    ensure_demo_data(outbox)

    # ──────────── Sidebar — filters ────────────
    with st.sidebar:
        st.subheader("Фильтры DLQ")
        transport_filter: str = st.text_input(
            "Транспорт", value="", help="http / kafka / grpc / webhook / soap / mqtt / ..."
        )
        action_filter: str = st.text_input("Действие", value="", help="Имя action или route")
        error_class_filter: str = st.text_input(
            "Класс ошибки",
            value="",
            help="Имя класса исключения (RuntimeError, TimeoutError, ...)",
        )
        tenant_filter: str = st.text_input("ID тенанта", value="", help="Tenant-контекст")
        hours_back: int = st.number_input(
            "За последние N часов", min_value=1, max_value=24 * 7, value=24, step=1
        )
        limit: int = st.number_input(
            "Лимит", min_value=10, max_value=1000, value=100, step=10
        )

    # ──────────── Загрузка DLQ ────────────
    since = datetime.now(timezone.utc) - timedelta(hours=int(hours_back))

    events: list[OutboxEvent] = list(
        run_async(
            outbox.list_dlq(
                transport=transport_filter or None,
                action=action_filter or None,
                error_class=error_class_filter or None,
                tenant_id=tenant_filter or None,
                since=since,
                limit=int(limit),
            )
        )
    )

    # ──────────── Сводка ────────────
    col_stats_1, col_stats_2, col_stats_3 = st.columns(3)
    col_stats_1.metric("Событий найдено", len(events))
    col_stats_2.metric("С payload", sum(1 for e in events if e.payload))
    col_stats_3.metric("Уникальных transports", len({e.transport for e in events}))

    # ──────────── Таблица событий ────────────
    st.subheader("События в DLQ")

    if not events:
        st.info("В DLQ нет событий по текущим фильтрам.")
        st.stop()

    rows: list[dict[str, Any]] = [
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
        for e in events
    ]

    st.dataframe(rows, width='stretch', hide_index=True)

    # ──────────── Bulk replay ────────────
    st.subheader("Массовый replay")

    event_id_options: list[str] = [e.event_id for e in events]
    event_label_by_id: dict[str, str] = {
        e.event_id: f"{e.transport}:{e.action} [{e.event_id[:8]}]" for e in events
    }

    selected_ids: list[str] = st.multiselect(
        "Выберите события для replay",
        options=event_id_options,
        format_func=lambda eid: event_label_by_id.get(eid, eid),
        help="События будут переведены из DLQ обратно в PENDING.",
    )

    col_bulk_1, col_bulk_2 = st.columns([1, 1])
    with col_bulk_1:
        dry_run_bulk: bool = st.checkbox("Пробный прогон", value=False, key="bulk_dry_run")
    with col_bulk_2:
        bulk_clicked = st.button(
            "Повторить выбранные",
            type="primary",
            disabled=not selected_ids,
            width='stretch',
        )

    if bulk_clicked and selected_ids:
        affected = run_async(outbox.replay(selected_ids, dry_run=dry_run_bulk))
        if dry_run_bulk:
            st.info(f"Dry-run: {affected} событий пройдёт replay.")
        else:
            st.success(f"Replay выполнен для {affected} событий.")
        st.rerun()

    # ──────────── Manual edit-and-replay ────────────
    st.subheader("Ручное edit-and-replay")

    manual_event_id: str = st.selectbox(
        "Событие",
        options=event_id_options,
        format_func=lambda eid: event_label_by_id.get(eid, eid),
        key="manual_event_id",
    )

    target_event: OutboxEvent | None = next(
        (e for e in events if e.event_id == manual_event_id), None
    )

    if target_event is not None:
        initial_payload = json.dumps(target_event.payload, ensure_ascii=False, indent=2)
        override_raw: str = st.text_area(
            "Переопределить payload (JSON)",
            value=initial_payload,
            height=200,
            help="Отредактируйте payload — он будет использован при replay.",
        )

        col_manual_1, col_manual_2 = st.columns([1, 1])
        with col_manual_1:
            dry_run_manual: bool = st.checkbox(
                "Пробный прогон", value=False, key="manual_dry_run"
            )
        with col_manual_2:
            manual_clicked = st.button(
                "Replay с переопределением", type="primary", width='stretch'
            )

        if manual_clicked:
            try:
                override_payload: dict[str, Any] = json.loads(override_raw)
            except json.JSONDecodeError as json_err:
                st.error(f"Невалидный JSON в override: {json_err}")
            else:
                affected = run_async(
                    outbox.replay(
                        [manual_event_id],
                        dry_run=dry_run_manual,
                        override_payload=override_payload,
                    )
                )
                if affected:
                    msg = (
                        "Dry-run: payload override применился бы"
                        if dry_run_manual
                        else "Replay с override выполнен"
                    )
                    st.success(msg)
                    if not dry_run_manual:
                        st.rerun()
                else:
                    st.warning(
                        "Событие не в DLQ или уже было перенесено — replay не выполнен."
                    )

    # ──────────── Подвал — текущий статус backend ────────────
    with st.expander("Информация о backend", expanded=False):
        st.write(f"Тип backend: `{type(outbox).__name__}`")
        if isinstance(outbox, FakeOutbox):
            stats = run_async(outbox.stats())
            st.write("Распределение по статусам:")
            st.json(
                {
                    OutboxEventStatus(k).value
                    if k in {s.value for s in OutboxEventStatus}
                    else k: v
                    for k, v in stats.items()
                }
            )
        st.caption(
            "Когда S5 К2 закоммитит OutboxDispatcher, DI-контейнер автоматически "
            "заменит Fake на production-backend (Postgres-table dlq_events)."
        )